import hashlib
import hmac
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.errors import ApiError

logger = logging.getLogger(__name__)
redis_client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)

_INCREMENT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {count, redis.call('TTL', KEYS[1])}
"""
_CHECK = """
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
return {count, redis.call('TTL', KEYS[1])}
"""


def _key(kind: str, identity: str) -> str:
    digest = hmac.new(
        settings.auth_secret_key.get_secret_value().encode(), identity.encode(), hashlib.sha256
    ).hexdigest()
    return f"cm:auth:{kind}:{digest}"


def _unavailable() -> ApiError:
    return ApiError(503, "AUTH_DEPENDENCY_UNAVAILABLE", "认证防护暂时不可用，请稍后重试")


def _enforce(count: int, limit: int, ttl: int) -> None:
    if count >= limit:
        logger.info("auth event=rate_limited")
        raise ApiError(
            429,
            "RATE_LIMITED",
            "尝试过于频繁，请稍后再试",
            headers={"Retry-After": str(max(ttl, 1))},
        )


async def check_login(ip: str, username: str) -> None:
    try:
        count, ttl = await redis_client.eval(
            _INCREMENT, 1, _key("ip", ip), settings.auth_login_ip_window
        )
        _enforce(count - 1, settings.auth_login_ip_limit, ttl)
        await check_password_attempt(username)
    except RedisError:
        raise _unavailable() from None


async def check_password_attempt(username: str) -> None:
    try:
        count, ttl = await redis_client.eval(_CHECK, 1, _key("failure", username))
        _enforce(count, settings.auth_login_failure_limit, ttl)
    except RedisError:
        raise _unavailable() from None


async def record_failure(username: str) -> None:
    try:
        await redis_client.eval(
            _INCREMENT, 1, _key("failure", username), settings.auth_login_failure_window
        )
    except RedisError:
        raise _unavailable() from None


async def record_success(username: str) -> None:
    try:
        await redis_client.delete(_key("failure", username))
    except RedisError:
        raise _unavailable() from None
