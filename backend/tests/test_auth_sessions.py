import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from test_auth_resources import resource_database as resource_database

from app.cli.auth import init_user, reset_password
from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import token_digest
from app.main import app
from app.models import AuthSession, User
from app.services import auth as service
from app.services import auth_rate_limit as limiter

PASSWORD = "authentication-test-password"
NEW_PASSWORD = "replacement-password-for-test"
ORIGIN = "http://localhost:5173"


@pytest.fixture
async def isolated_redis(monkeypatch: pytest.MonkeyPatch):
    url = os.environ.get("CREATORMIND_TEST_REDIS_URL")
    if not url:
        pytest.skip("Session integration requires explicit CREATORMIND_TEST_REDIS_URL")
    client = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
    prefix = "auth_session_test:" + uuid4().hex + ":"
    original = limiter._key
    monkeypatch.setattr(limiter, "_key", lambda kind, identity: prefix + original(kind, identity))
    monkeypatch.setattr(limiter, "redis_client", client)
    try:
        await client.ping()
        yield client
    finally:
        keys = [key async for key in client.scan_iter(match=prefix + "*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


def browser() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
        headers={"Origin": ORIGIN},
    )


async def login(client: httpx.AsyncClient, password: str = PASSWORD):
    csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
    client.headers["X-CSRF-Token"] = csrf
    response = await client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": password}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


async def account(sessions):
    async with sessions() as db:
        return await init_user(db, "alice", PASSWORD)


async def test_login_current_logout_and_password_rotation(
    resource_database, isolated_redis
) -> None:
    sessions = resource_database
    user = await account(sessions)
    async with browser() as a, browser() as b:
        await login(a)
        await login(b)
        token = a.cookies.get(settings.session_cookie_name)
        async with sessions() as db:
            stored = await db.scalar(
                select(AuthSession).where(AuthSession.token_hash == token_digest(token))
            )
            assert stored is not None and stored.token_hash != token
            assert stored.user_id == user.id
        assert (await a.get("/api/v1/auth/me")).status_code == 200
        assert (await a.post("/api/v1/auth/logout")).status_code == 204
        assert (await a.get("/api/v1/auth/me")).status_code == 401
        assert (await b.get("/api/v1/auth/me")).status_code == 200
        await login(a)
        old_token = a.cookies.get(settings.session_cookie_name)
        changed = await a.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert changed.status_code == 200
        a.headers["X-CSRF-Token"] = changed.json()["csrf_token"]
        assert a.cookies.get(settings.session_cookie_name) != old_token
        assert (await a.get("/api/v1/auth/me")).status_code == 200
        assert (await b.get("/api/v1/auth/me")).status_code == 401
        async with sessions() as db:
            await reset_password(db, "alice", "admin-reset-test-password")
        assert (await a.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.parametrize("reason", ["expired", "version", "inactive"])
async def test_session_rechecks_expiry_version_and_user_status(
    reason,
    resource_database,
    isolated_redis,
) -> None:
    sessions = resource_database
    user = await account(sessions)
    async with browser() as client:
        await login(client)
        async with sessions() as db, db.begin():
            current = await db.get(User, user.id)
            if reason == "inactive":
                current.is_active = False
            elif reason == "version":
                current.auth_version += 1
            else:
                session = await db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
                session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["code"] == "SESSION_INVALID"
        assert "set-cookie" not in response.headers


async def test_redis_atomic_limit_and_fail_closed(
    isolated_redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_login_ip_limit", 2)
    results = await asyncio.gather(
        *(limiter.check_login("test-ip", "alice") for _ in range(6)), return_exceptions=True
    )
    assert sum(result is None for result in results) == 2
    failures = [result for result in results if isinstance(result, ApiError)]
    assert len(failures) == 4 and all(result.status == 429 for result in failures)

    class UnavailableRedis:
        async def eval(self, *args):
            raise RedisConnectionError("test-disconnected")

    monkeypatch.setattr(limiter, "redis_client", UnavailableRedis())
    with pytest.raises(ApiError) as caught:
        await limiter.check_login("other-ip", "alice")
    assert caught.value.status == 503
    assert caught.value.code == "AUTH_DEPENDENCY_UNAVAILABLE"


async def test_logout_waits_for_authorized_transaction(resource_database, isolated_redis) -> None:
    sessions = resource_database
    await account(sessions)
    async with browser() as client:
        await login(client)
        token = client.cookies.get(settings.session_cookie_name)

    async def revoke():
        async with sessions() as db:
            await service.logout(db, token)

    async with sessions() as authorized:
        await service.authenticate(authorized, token)
        task = asyncio.create_task(revoke())
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
            await authorized.commit()
            await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with sessions() as db:
        with pytest.raises(ApiError) as caught:
            await service.authenticate(db, token)
        assert caught.value.status == 401


async def test_reset_during_password_check_cannot_create_old_session(
    resource_database,
    isolated_redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = resource_database
    await account(sessions)
    verified = asyncio.Event()
    resume = asyncio.Event()
    original = service.verify_password

    async def paused_verify(encoded, password):
        result = await original(encoded, password)
        verified.set()
        await resume.wait()
        return result

    monkeypatch.setattr(service, "verify_password", paused_verify)

    async def old_login():
        async with sessions() as db:
            return await service.login(db, "alice", PASSWORD, None, "test-ip")

    task = asyncio.create_task(old_login())
    try:
        await asyncio.wait_for(verified.wait(), timeout=5)
        async with sessions() as db:
            await reset_password(db, "alice", NEW_PASSWORD)
        resume.set()
        with pytest.raises(ApiError) as caught:
            await asyncio.wait_for(task, timeout=5)
        assert caught.value.status == 401
        async with sessions() as db:
            assert await db.scalar(select(AuthSession)) is None
    finally:
        resume.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
