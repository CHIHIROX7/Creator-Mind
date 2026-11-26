"""Password hashing and high-entropy session credentials."""

import asyncio
import base64
import hashlib
import re
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from weakref import WeakKeyDictionary

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from argon2.low_level import Type

_USERNAME = re.compile(r"[a-z0-9][a-z0-9_-]{2,31}", re.ASCII)
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="auth-password")
_LIMITERS: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = WeakKeyDictionary()
_LIMITERS_LOCK = threading.Lock()
_DUMMY_LOCK = threading.Lock()
_dummy_hash: str | None = None


def normalize_username(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("用户名必须是字符串。")
    normalized = value.strip().lower()
    if not value.strip().isascii() or _USERNAME.fullmatch(normalized) is None:
        raise ValueError("用户名需为3–32位ASCII字母、数字、下划线或连字符，首位为字母或数字。")
    return normalized


def validate_password(value: str) -> str:
    if not isinstance(value, str) or not 15 <= len(value) <= 128:
        raise ValueError("密码长度必须为15–128个字符；不会裁剪空格或截断密码。")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("密码包含无法编码的字符。") from None
    return value


async def _password_work[Result](operation: Callable[[], Result]) -> Result:
    loop = asyncio.get_running_loop()
    with _LIMITERS_LOCK:
        limiter = _LIMITERS.setdefault(loop, asyncio.Semaphore(2))
    await limiter.acquire()
    try:
        future = _EXECUTOR.submit(operation)
    except BaseException:
        limiter.release()
        raise

    def release_slot(_future: object) -> None:
        try:
            loop.call_soon_threadsafe(limiter.release)
        except RuntimeError:
            pass

    future.add_done_callback(release_slot)
    return await asyncio.wrap_future(future, loop=loop)


async def hash_password(password: str) -> str:
    password = validate_password(password)
    return await _password_work(lambda: _PASSWORD_HASHER.hash(password))


def _verify(encoded: str, password: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(encoded, password)
    except (Argon2Error, InvalidHashError, UnicodeEncodeError, TypeError):
        return False


async def verify_password(encoded: str, password: str) -> bool:
    if not isinstance(encoded, str) or not isinstance(password, str):
        return False
    return await _password_work(lambda: _verify(encoded, password))


def _verify_dummy(password: str) -> None:
    global _dummy_hash
    with _DUMMY_LOCK:
        if _dummy_hash is None:
            _dummy_hash = _PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
        encoded = _dummy_hash
    _verify(encoded, password)


async def verify_dummy_password(password: str) -> None:
    await _password_work(lambda: _verify_dummy(password))


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def valid_token(token: str | None) -> bool:
    if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
        return False
    decoded = base64.urlsafe_b64decode(token + "=")
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    return len(decoded) == 32 and canonical == token
