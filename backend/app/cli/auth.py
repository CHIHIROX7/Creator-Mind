"""Local-only identity initialization, password reset, and session maintenance."""

import argparse
import asyncio
import getpass
import hmac
import sys
import warnings
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, normalize_username, validate_password
from app.models.auth_session import AuthSession
from app.models.user import User

INIT_USER_LOCK_KEY = 0x434D41555448


class AuthCommandError(Exception):
    """An intentionally safe error message for a local administration operation."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, "参数无效；密码仅能通过隐藏输入提供，不支持命令行密码参数。\n")


async def init_user(db: AsyncSession, username: str, password: str) -> User:
    username = normalize_username(username)
    encoded = await hash_password(password)
    async with db.begin():
        await db.execute(select(func.pg_advisory_xact_lock(INIT_USER_LOCK_KEY)))
        if await db.scalar(select(User.id).limit(1)) is not None:
            raise AuthCommandError("账号已存在，拒绝再次初始化。")
        user = User(username=username, password_hash=encoded, is_active=True, auth_version=1)
        db.add(user)
        await db.flush()
    return user


async def reset_password(db: AsyncSession, username: str, password: str) -> User:
    username = normalize_username(username)
    encoded = await hash_password(password)
    async with db.begin():
        user = await db.scalar(select(User).where(User.username == username).with_for_update())
        if user is None:
            raise AuthCommandError("指定账号不存在。")
        now = datetime.now(UTC)
        user.password_hash = encoded
        user.auth_version += 1
        user.updated_at = now
        await db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.flush()
    return user


async def cleanup_sessions(db: AsyncSession) -> int:
    async with db.begin():
        result = await db.execute(
            delete(AuthSession).where(
                or_(
                    AuthSession.expires_at <= datetime.now(UTC), AuthSession.revoked_at.is_not(None)
                )
            )
        )
    return result.rowcount


def _read_password() -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        password = getpass.getpass("密码（15–128字符，不裁剪空格）：")
        confirmation = getpass.getpass("再次输入密码：")
    validate_password(password)
    validate_password(confirmation)
    if not hmac.compare_digest(password.encode("utf-8"), confirmation.encode("utf-8")):
        raise AuthCommandError("两次密码输入不一致。")
    return password


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description="本机账号管理；密码只能通过隐藏输入提供。")
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("init-user", "初始化唯一账号"),
        ("reset-password", "重置密码并撤销该账号的全部会话"),
    ):
        subparser = commands.add_parser(command, help=help_text)
        subparser.add_argument("--username", required=True)
    commands.add_parser("cleanup-sessions", help="删除已过期或已撤销的会话")
    return parser


async def _run(command: str, username: str | None, password: str | None) -> str:
    from app.db.session import SessionLocal, engine

    try:
        async with SessionLocal() as db:
            if command == "init-user":
                if username is None or password is None:
                    raise AuthCommandError("缺少账号或隐藏输入的密码，操作已取消。")
                user = await init_user(db, username, password)
                return f"账号 {user.username} 初始化完成；请通过浏览器登录。"
            if command == "reset-password":
                if username is None or password is None:
                    raise AuthCommandError("缺少账号或隐藏输入的密码，操作已取消。")
                user = await reset_password(db, username, password)
                return f"账号 {user.username} 密码已重置；全部登录会话已失效。"
            count = await cleanup_sessions(db)
            return f"已清理 {count} 条过期或撤销的会话。"
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        username = normalize_username(args.username) if hasattr(args, "username") else None
        password = _read_password() if username is not None else None
        message = asyncio.run(_run(args.command, username, password))
    except AuthCommandError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError:
        print("用户名或密码不符合规则；用户名3–32位ASCII，密码15–128字符。", file=sys.stderr)
        return 1
    except getpass.GetPassWarning:
        print("当前终端不支持隐藏密码输入，操作已取消。", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("操作已取消。", file=sys.stderr)
        return 1
    except Exception:
        print("操作失败；请检查本机数据库配置和连接，未输出凭证或内部异常。", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
