import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import Request, Response

from app.core.config import Settings, settings
from app.core.errors import ApiError
from app.core.security import token_digest, valid_token


def check_origin(request: Request, *, allow_referer: bool = False) -> None:
    origin = request.headers.get("origin")
    if origin is None and allow_referer:
        referer = request.headers.get("referer", "")
        parsed = urlsplit(referer)
        if parsed.scheme and parsed.netloc and not parsed.username and not parsed.password:
            origin = f"{parsed.scheme}://{parsed.netloc}"
    if (
        origin not in settings.auth_origin_list
        or request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise ApiError(403, "ORIGIN_FORBIDDEN", "请求来源不受信任")


def _scope(session_token: str | None) -> str:
    return token_digest(session_token) if valid_token(session_token) else "anonymous"


def _signature(payload: str, session_token: str | None, config: Settings) -> str:
    message = f"csrf:{_scope(session_token)}:{payload}".encode()
    return hmac.new(
        config.auth_secret_key.get_secret_value().encode(), message, hashlib.sha256
    ).hexdigest()


def create_csrf(
    session_token: str | None, *, config: Settings = settings, now: int | None = None
) -> tuple[str, datetime]:
    issued_at = int(time.time()) if now is None else now
    payload = f"{issued_at}.{secrets.token_urlsafe(32)}"
    token = f"{payload}.{_signature(payload, session_token, config)}"
    return token, datetime.fromtimestamp(issued_at + config.auth_csrf_ttl_seconds, UTC)


def verify_csrf(
    token: str,
    cookie: str,
    session_token: str | None,
    *,
    config: Settings = settings,
    now: int | None = None,
) -> bool:
    if not token or len(token) > 200 or not token.isascii() or not cookie.isascii():
        return False
    if not hmac.compare_digest(token, cookie):
        return False
    try:
        timestamp, nonce, signature = token.split(".")
        issued_at = int(timestamp)
    except (ValueError, TypeError):
        return False
    current = int(time.time()) if now is None else now
    if not 0 <= current - issued_at < config.auth_csrf_ttl_seconds or not valid_token(nonce):
        return False
    expected = _signature(f"{timestamp}.{nonce}", session_token, config)
    return hmac.compare_digest(expected, signature)


def require_csrf(request: Request) -> None:
    check_origin(request)
    if not verify_csrf(
        request.headers.get("x-csrf-token", ""),
        request.cookies.get(settings.csrf_cookie_name, ""),
        request.cookies.get(settings.session_cookie_name),
    ):
        raise ApiError(403, "CSRF_INVALID", "安全凭证已失效，请重新获取后再次提交")


def set_auth_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name, value, httponly=True, secure=settings.auth_cookie_secure, samesite="lax", path="/"
    )


def issue_csrf(response: Response, session_token: str | None) -> tuple[str, datetime]:
    token, expires_at = create_csrf(session_token)
    set_auth_cookie(response, settings.csrf_cookie_name, token)
    response.headers["Cache-Control"] = "no-store"
    return token, expires_at


def clear_auth_cookies(response: Response) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(
            name, path="/", secure=settings.auth_cookie_secure, httponly=True, samesite="lax"
        )
    response.headers["Cache-Control"] = "no-store"
