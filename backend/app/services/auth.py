import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import (
    generate_token,
    hash_password,
    token_digest,
    valid_token,
    verify_dummy_password,
    verify_password,
)
from app.models.auth_session import AuthSession
from app.models.user import User
from app.services import auth_rate_limit

logger = logging.getLogger(__name__)


@dataclass
class Identity:
    user: User
    session: AuthSession


def _invalid() -> ApiError:
    return ApiError(401, "SESSION_INVALID", "登录已失效，请重新登录")


def _is_valid(user: User, session: AuthSession) -> bool:
    return (
        user.is_active
        and session.revoked_at is None
        and session.expires_at > datetime.now(UTC)
        and session.auth_version == user.auth_version
    )


async def authenticate(db: AsyncSession, token: str | None, *, exclusive: bool = False) -> Identity:
    if not token:
        raise ApiError(401, "AUTH_REQUIRED", "请先登录")
    if not valid_token(token):
        raise _invalid()
    session = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_digest(token))
    )
    if session is None:
        raise _invalid()
    user = await db.scalar(
        select(User)
        .where(User.id == session.user_id)
        .with_for_update(read=not exclusive)
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise _invalid()
    session = await db.scalar(
        select(AuthSession)
        .where(AuthSession.token_hash == token_digest(token))
        .with_for_update(read=not exclusive)
        .execution_options(populate_existing=True)
    )
    if session is None or not _is_valid(user, session):
        raise _invalid()
    return Identity(user, session)


async def _has_valid_session(db: AsyncSession, token: str | None) -> bool:
    if not valid_token(token):
        return False
    result = await db.execute(
        select(User, AuthSession)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.token_hash == token_digest(token))
    )
    row = result.first()
    return row is not None and _is_valid(row[0], row[1])


def _new_session(db: AsyncSession, user: User) -> tuple[AuthSession, str]:
    token = generate_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=token_digest(token),
        auth_version=user.auth_version,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.auth_session_ttl_seconds),
    )
    db.add(session)
    return session, token


async def login(
    db: AsyncSession, username: str, password: str, token: str | None, ip: str
) -> tuple[Identity, str]:
    await auth_rate_limit.check_login(ip, username)
    if await _has_valid_session(db, token):
        raise ApiError(409, "ALREADY_AUTHENTICATED", "当前浏览器已经登录")
    user = await db.scalar(select(User).where(User.username == username))
    if user is None:
        await verify_dummy_password(password)
        verified = False
        old_hash = ""
        old_version = 0
    else:
        old_hash, old_version = user.password_hash, user.auth_version
        verified = await verify_password(old_hash, password)
    if user is None or not verified or not user.is_active:
        await auth_rate_limit.record_failure(username)
        logger.info("auth event=login_failed")
        raise ApiError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    user = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        user is None
        or not user.is_active
        or user.password_hash != old_hash
        or user.auth_version != old_version
    ):
        await auth_rate_limit.record_failure(username)
        raise ApiError(401, "INVALID_CREDENTIALS", "用户名或密码错误")
    await auth_rate_limit.record_success(username)
    session, new_token = _new_session(db, user)
    await db.commit()
    logger.info("auth event=login_success user_id=%s session_id=%s", user.id, session.id)
    return Identity(user, session), new_token


async def logout(db: AsyncSession, token: str | None) -> None:
    if not valid_token(token):
        return
    session = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_digest(token))
    )
    if session is None:
        return
    user = await db.scalar(
        select(User).where(User.id == session.user_id).with_for_update(read=True)
    )
    if user is None:
        return
    session = await db.scalar(
        select(AuthSession)
        .where(AuthSession.token_hash == token_digest(token))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.commit()
        logger.info("auth event=logout user_id=%s session_id=%s", user.id, session.id)


async def change_password(
    db: AsyncSession, token: str | None, current_password: str, new_password: str
) -> tuple[Identity, str]:
    identity = await authenticate(db, token, exclusive=True)
    user = identity.user
    await auth_rate_limit.check_password_attempt(user.username)
    if not await verify_password(user.password_hash, current_password):
        await auth_rate_limit.record_failure(user.username)
        raise ApiError(400, "INVALID_CURRENT_PASSWORD", "当前密码错误")
    encoded = await hash_password(new_password)
    await auth_rate_limit.record_success(user.username)
    user.password_hash = encoded
    user.auth_version += 1
    user.updated_at = datetime.now(UTC)
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    session, new_token = _new_session(db, user)
    await db.commit()
    logger.info("auth event=password_changed user_id=%s session_id=%s", user.id, session.id)
    return Identity(user, session), new_token
