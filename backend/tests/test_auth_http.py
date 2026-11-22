import secrets

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings, settings
from app.core.csrf import create_csrf, verify_csrf
from app.core.security import generate_token
from app.main import app

ORIGIN = "http://localhost:5173"


def test_csrf_scope_expiry_and_tamper() -> None:
    token = generate_token()
    csrf, _ = create_csrf(token, now=1000)
    assert verify_csrf(csrf, csrf, token, now=1001)
    assert not verify_csrf(csrf, csrf, generate_token(), now=1001)
    assert not verify_csrf(csrf, csrf, token, now=2800)
    assert not verify_csrf(csrf, csrf, token, now=999)
    assert not verify_csrf(csrf + "x", csrf + "x", token, now=1001)
    assert not verify_csrf(csrf, "wrong", token, now=1001)
    anonymous, _ = create_csrf(None, now=1000)
    assert verify_csrf(anonymous, anonymous, None, now=1001)
    assert not verify_csrf(anonymous, anonymous, token, now=1001)


def test_auth_config_requires_safe_secret_and_explicit_origins() -> None:
    config = Settings(_env_file=None, auth_secret_key=SecretStr(""))
    with pytest.raises(ValueError):
        config.validate_auth()
    config.auth_secret_key = SecretStr(secrets.token_urlsafe(48))
    config.validate_auth()
    config.auth_trusted_origins = "http://localhost:5173.evil"
    with pytest.raises(ValueError):
        config.validate_auth()
    config.auth_trusted_origins = ORIGIN
    config.environment = "production"
    config.debug = False
    with pytest.raises(ValueError):
        config.validate_auth()


def test_origin_csrf_and_cookie_contract() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/csrf").status_code == 403
        assert (
            client.get("/api/v1/auth/csrf", headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        response = client.get("/api/v1/auth/csrf", headers={"Referer": ORIGIN + "/login"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie
        assert "max-age" not in cookie and "domain=" not in cookie
        assert client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN}).status_code == 403
        response = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]},
        )
        assert response.status_code == 204
        assert settings.csrf_cookie_name not in client.cookies


def test_anonymous_private_access_and_no_cookie_deletion() -> None:
    with TestClient(app) as client:
        for path in ("/api/v1/auth/me", "/api/v1/conversations"):
            response = client.get(path)
            assert response.status_code == 401
            assert response.json()["code"] == "AUTH_REQUIRED"
            assert "set-cookie" not in response.headers
            assert response.headers["cache-control"] == "no-store"


def test_validation_does_not_echo_passwords_or_extra_fields() -> None:
    secret = "do-not-leak-this-password"
    with TestClient(app) as client:
        csrf = client.get("/api/v1/auth/csrf", headers={"Origin": ORIGIN}).json()["csrf_token"]
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"username": "not valid!", "password": secret, "unexpected": secret},
        )
        assert response.status_code == 422
        assert secret not in response.text
        assert "input" not in response.text


def test_untrusted_host_and_oversized_payload() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"Host": "evil.example"})
        assert response.status_code == 400
        response = client.post(
            "/api/v1/auth/login",
            content=b"x" * 131073,
            headers={"Origin": ORIGIN, "Content-Type": "application/json"},
        )
        assert response.status_code == 413


def test_database_failure_never_returns_private_exception() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from app.db.session import get_db

    secret = "do-not-leak-db-password-or-parameters"

    async def failed_database():
        raise SQLAlchemyError(secret)
        yield

    app.dependency_overrides[get_db] = failed_database
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/auth/me")
            assert response.status_code == 503
            assert response.json()["code"] == "AUTH_DEPENDENCY_UNAVAILABLE"
            assert secret not in response.text
            assert "set-cookie" not in response.headers
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_production_cookie_is_secure_and_host_only(monkeypatch: pytest.MonkeyPatch) -> None:
    origin = "https://creator.example"
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "auth_trusted_origins", origin)
    monkeypatch.setattr(settings, "cors_origins", origin)
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/csrf", headers={"Origin": origin})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert cookie.startswith("__Host-cm_csrf=")
        assert "Secure" in cookie and "HttpOnly" in cookie and "Path=/" in cookie
        assert "Domain=" not in cookie and "Max-Age=" not in cookie
