import asyncio
import hashlib
import threading
import time
from types import SimpleNamespace

import pytest
from argon2 import extract_parameters
from argon2.low_level import Type

from app.core import security

PASSWORD = " long-password-密碼 "


@pytest.mark.parametrize("value", ["abc", " A_B-123 ", "A" * 32])
def test_username_normalization(value: str) -> None:
    assert security.normalize_username(value) == value.strip().lower()


@pytest.mark.parametrize(
    "value", ["", "ab", "a" * 33, "_abc", "-abc", "a b", "admin@example", "用户名", "Kelvin"]
)
def test_invalid_username(value: str) -> None:
    with pytest.raises(ValueError):
        security.normalize_username(value)


@pytest.mark.parametrize("password", [" " * 15, PASSWORD, "界" * 128])
def test_password_is_preserved(password: str) -> None:
    assert security.validate_password(password) == password


@pytest.mark.parametrize("password", ["", "a" * 14, "a" * 129, "a" * 14 + "\ud800"])
def test_password_validation_does_not_echo(password: str) -> None:
    with pytest.raises(ValueError) as caught:
        security.validate_password(password)
    if password:
        assert password not in str(caught.value)


async def test_argon2_parameters_salt_and_verification() -> None:
    first = await security.hash_password(PASSWORD)
    second = await security.hash_password(PASSWORD)
    assert first != second
    parameters = extract_parameters(first)
    assert parameters.type is Type.ID
    assert (parameters.memory_cost, parameters.time_cost, parameters.parallelism) == (65536, 3, 1)
    assert parameters.salt_len >= 16
    assert await security.verify_password(first, PASSWORD)
    assert not await security.verify_password(first, PASSWORD.strip())
    assert not await security.verify_password(first, "wrong-password-value")
    assert not await security.verify_password("invalid encoded hash", PASSWORD)


async def test_dummy_hash_has_real_parameters_and_is_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security, "_dummy_hash", None)
    assert await security.verify_dummy_password(PASSWORD) is None
    encoded = security._dummy_hash
    assert encoded is not None
    assert extract_parameters(encoded) == extract_parameters(await security.hash_password(PASSWORD))
    assert await security.verify_dummy_password("another-wrong-password") is None
    assert security._dummy_hash == encoded
    assert not await security.verify_password(encoded, PASSWORD)


def test_random_token_format_and_digest() -> None:
    tokens = {security.generate_token() for _ in range(100)}
    assert len(tokens) == 100
    for token in tokens:
        assert len(token) == 43
        assert security.valid_token(token)
        assert security.token_digest(token) == hashlib.sha256(token.encode("ascii")).hexdigest()
        assert len(security.token_digest(token)) == 64


@pytest.mark.parametrize(
    "token", [None, "", "a" * 42, "a" * 44, "a" * 43, "=" * 43, "界" * 43, "A" * 42 + "B"]
)
def test_reject_invalid_or_noncanonical_tokens(token: str | None) -> None:
    assert not security.valid_token(token)


async def test_password_work_is_off_loop_and_has_two_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = threading.Lock()
    thread_ids: set[int] = set()
    running = 0
    peak = 0
    ticks = 0
    done = False

    def fake_hash(password: str) -> str:
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
            thread_ids.add(threading.get_ident())
        time.sleep(0.05)
        with guard:
            running -= 1
        return "encoded"

    async def heartbeat() -> None:
        nonlocal ticks
        while not done:
            ticks += 1
            await asyncio.sleep(0.005)

    monkeypatch.setattr(security, "_PASSWORD_HASHER", SimpleNamespace(hash=fake_hash))
    heart = asyncio.create_task(heartbeat())
    try:
        results = await asyncio.gather(*(security.hash_password(PASSWORD) for _ in range(8)))
    finally:
        done = True
        await heart
    assert results == ["encoded"] * 8
    assert peak == 2
    assert len(thread_ids) == 2
    assert threading.get_ident() not in thread_ids
    assert ticks >= 5


async def test_cancelled_work_does_not_release_a_running_slot() -> None:
    started = threading.Event()
    release = threading.Event()

    def blocked() -> bool:
        started.set()
        return release.wait(3)

    task = asyncio.create_task(security._password_work(blocked))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        limiter = security._LIMITERS[asyncio.get_running_loop()]
        assert limiter._value == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert limiter._value == 1
    finally:
        release.set()
        for _ in range(100):
            if security._LIMITERS[asyncio.get_running_loop()]._value == 2:
                break
            await asyncio.sleep(0.005)
    assert security._LIMITERS[asyncio.get_running_loop()]._value == 2
