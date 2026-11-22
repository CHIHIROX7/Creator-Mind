import asyncio
import importlib.util
import os
import warnings
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema, DropSchema

from app.cli import auth
from app.core.security import generate_token, token_digest, verify_password
from app.db.base import Base
from app.models import AuthSession, Conversation, User

PASSWORD = "long-test-password-密碼"
NEW_PASSWORD = "another-long-test-password"


def _mock_db() -> MagicMock:
    db = MagicMock(spec=AsyncSession)
    db.scalar = AsyncMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    return db


async def test_init_takes_advisory_lock_and_only_creates_if_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _mock_db()
    db.scalar.return_value = None
    monkeypatch.setattr(auth, "hash_password", AsyncMock(return_value="encoded-hash"))
    user = await auth.init_user(db, " Admin ", PASSWORD)
    assert user.username == "admin"
    assert user.password_hash == "encoded-hash"
    assert user.auth_version == 1
    lock = db.execute.call_args_list[0].args[0]
    assert "pg_advisory_xact_lock" in str(lock)
    assert auth.INIT_USER_LOCK_KEY in lock.compile().params.values()
    db.add.assert_called_once_with(user)
    db.begin.return_value.__aexit__.assert_awaited_once_with(None, None, None)


async def test_existing_account_refuses_initialization(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _mock_db()
    db.scalar.return_value = uuid4()
    monkeypatch.setattr(auth, "hash_password", AsyncMock(return_value="encoded-hash"))
    with pytest.raises(auth.AuthCommandError, match="账号已存在"):
        await auth.init_user(db, "admin", PASSWORD)
    db.add.assert_not_called()
    assert db.begin.return_value.__aexit__.call_args.args[0] is auth.AuthCommandError


async def test_reset_locks_user_and_revokes_all_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _mock_db()
    user = User(id=uuid4(), username="admin", password_hash="old-hash", auth_version=4)
    db.scalar.return_value = user
    monkeypatch.setattr(auth, "hash_password", AsyncMock(return_value="new-hash"))
    result = await auth.reset_password(db, " Admin ", NEW_PASSWORD)
    query = db.scalar.call_args.args[0]
    assert "FOR UPDATE" in str(query.compile(dialect=postgresql.dialect()))
    assert result is user
    assert user.password_hash == "new-hash"
    assert user.auth_version == 5
    revoke = db.execute.call_args.args[0]
    assert "auth_sessions.revoked_at IS NULL" in str(revoke)
    assert user.id in revoke.compile().params.values()
    db.begin.return_value.__aexit__.assert_awaited_once_with(None, None, None)


async def test_missing_user_reset_is_rolled_back(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _mock_db()
    db.scalar.return_value = None
    monkeypatch.setattr(auth, "hash_password", AsyncMock(return_value="new-hash"))
    with pytest.raises(auth.AuthCommandError, match="不存在"):
        await auth.reset_password(db, "admin", NEW_PASSWORD)
    db.execute.assert_not_awaited()
    assert db.begin.return_value.__aexit__.call_args.args[0] is auth.AuthCommandError


async def test_cleanup_deletes_expired_or_revoked_sessions() -> None:
    db = _mock_db()
    db.execute.return_value.rowcount = 7
    assert await auth.cleanup_sessions(db) == 7
    query = str(db.execute.call_args.args[0])
    assert "expires_at <=" in query
    assert "revoked_at IS NOT NULL" in query
    assert " OR " in query


@pytest.mark.parametrize("command", ["init-user", "reset-password"])
def test_cli_reads_two_hidden_passwords_without_echo(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    hidden = MagicMock(side_effect=[PASSWORD, PASSWORD])
    runner = AsyncMock(return_value="操作完成。")
    monkeypatch.setattr(auth.getpass, "getpass", hidden)
    monkeypatch.setattr(auth, "_run", runner)
    assert auth.main([command, "--username", " Admin "]) == 0
    assert hidden.call_count == 2
    runner.assert_awaited_once_with(command, "admin", PASSWORD)
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err


def test_cli_mismatched_passwords_never_calls_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    runner = AsyncMock()
    monkeypatch.setattr(auth.getpass, "getpass", MagicMock(side_effect=[PASSWORD, NEW_PASSWORD]))
    monkeypatch.setattr(auth, "_run", runner)
    assert auth.main(["init-user", "--username", "admin"]) == 1
    runner.assert_not_called()
    captured = capsys.readouterr()
    assert "不一致" in captured.err
    assert PASSWORD not in captured.out + captured.err
    assert NEW_PASSWORD not in captured.out + captured.err


def test_cli_refuses_password_parameters_without_echo(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        auth.main(["init-user", "--username", "admin", "--password", PASSWORD])
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err


def test_cli_database_error_does_not_leak_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(auth.getpass, "getpass", MagicMock(side_effect=[PASSWORD, PASSWORD]))
    monkeypatch.setattr(auth, "_run", AsyncMock(side_effect=SQLAlchemyError(PASSWORD)))
    assert auth.main(["reset-password", "--username", "admin"]) == 1
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err
    assert "Traceback" not in captured.err


def test_cli_fails_closed_when_hidden_input_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def unsafe_prompt(prompt: str) -> str:
        warnings.warn("hidden input unavailable", auth.getpass.GetPassWarning, stacklevel=2)
        pytest.fail("must not fall back to visible input")

    monkeypatch.setattr(auth.getpass, "getpass", unsafe_prompt)
    runner = AsyncMock()
    monkeypatch.setattr(auth, "_run", runner)
    assert auth.main(["init-user", "--username", "admin"]) == 1
    runner.assert_not_called()
    assert "不支持隐藏" in capsys.readouterr().err


def test_cleanup_never_prompts_for_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    hidden = MagicMock()
    runner = AsyncMock(return_value="已清理0条会话。")
    monkeypatch.setattr(auth.getpass, "getpass", hidden)
    monkeypatch.setattr(auth, "_run", runner)
    assert auth.main(["cleanup-sessions"]) == 0
    hidden.assert_not_called()
    runner.assert_awaited_once_with("cleanup-sessions", None, None)


@pytest.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    url = os.getenv("CREATORMIND_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set CREATORMIND_TEST_DATABASE_URL to an explicit PostgreSQL test database")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("CREATORMIND_TEST_DATABASE_URL must use postgresql+asyncpg")
    schema = "auth_identity_test_" + uuid4().hex
    engine = create_async_engine(
        url, poolclass=NullPool, echo=False, hide_parameters=True,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await engine.dispose()


async def _create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def test_pg_concurrent_initialization_creates_one_account(pg_engine: AsyncEngine) -> None:
    await _create_tables(pg_engine)
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def initialize(username: str) -> User:
        async with sessions() as db:
            return await auth.init_user(db, username, PASSWORD)

    results = await asyncio.gather(initialize("admin"), initialize("other"), return_exceptions=True)
    assert sum(isinstance(result, User) for result in results) == 1
    assert sum(isinstance(result, auth.AuthCommandError) for result in results) == 1
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 1


async def test_pg_reset_revokes_sessions_and_cleanup_preserves_active(
    pg_engine: AsyncEngine,
) -> None:
    await _create_tables(pg_engine)
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with sessions() as db:
        user = await auth.init_user(db, "admin", PASSWORD)
    now = datetime.now(UTC)
    async with sessions() as db, db.begin():
        for expires in [now + timedelta(hours=1), now - timedelta(hours=1)]:
            db.add(AuthSession(user_id=user.id, token_hash=token_digest(generate_token()),
                               auth_version=1, expires_at=expires))
    async with sessions() as db:
        changed = await auth.reset_password(db, "ADMIN", NEW_PASSWORD)
    assert changed.auth_version == 2
    assert await verify_password(changed.password_hash, NEW_PASSWORD)
    assert not await verify_password(changed.password_hash, PASSWORD)
    async with sessions() as db:
        stored = list((await db.scalars(select(AuthSession))).all())
        assert len(stored) == 2
        assert all(session.revoked_at is not None for session in stored)
    async with sessions() as db, db.begin():
        db.add(AuthSession(user_id=user.id, token_hash=token_digest(generate_token()),
                           auth_version=2, expires_at=now + timedelta(hours=1)))
    async with sessions() as db:
        assert await auth.cleanup_sessions(db) == 2
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuthSession)) == 1


async def test_pg_conversation_owner_is_not_nullable_and_delete_is_restricted(
    pg_engine: AsyncEngine,
) -> None:
    await _create_tables(pg_engine)
    sessions = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with sessions() as db:
        user = await auth.init_user(db, "admin", PASSWORD)
    async with sessions() as db, db.begin():
        db.add(Conversation(user_id=user.id, title="owned conversation"))
    with pytest.raises(DBAPIError):
        async with sessions() as db, db.begin():
            await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    with pytest.raises(DBAPIError):
        async with sessions() as db, db.begin():
            db.add(Conversation(title="unowned conversation"))
            await db.flush()


def _revision(filename: str) -> ModuleType:
    path = Path(__file__).parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("identity_test_" + filename[:-3], path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(connection: object, module: ModuleType) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


def test_migration_offline_sql_contains_locked_legacy_guard_before_ddl() -> None:
    current = _revision("20261122_0003_user_auth.py")
    output = StringIO()
    context = MigrationContext.configure(
        url="postgresql+asyncpg://",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        current.upgrade()
    sql = output.getvalue()
    assert current.down_revision == "20261120_0002"
    assert sql.index("LOCK TABLE conversations") < sql.index("IF EXISTS")
    assert sql.index("IF EXISTS") < sql.index("CREATE TABLE users")
    assert "existing conversations" in sql
    assert "ON DELETE RESTRICT" in sql
    assert "ADD COLUMN user_id UUID NOT NULL" in sql
    assert "TRUNCATE" not in sql and "DELETE FROM" not in sql


@pytest.mark.parametrize("has_legacy_data", [False, True])
async def test_pg_migration_empty_success_and_legacy_data_refusal(
    pg_engine: AsyncEngine, has_legacy_data: bool,
) -> None:
    previous = _revision("20261120_0002_conversations.py")
    current = _revision("20261122_0003_user_auth.py")
    old_id = uuid4()
    async with pg_engine.begin() as connection:
        await connection.run_sync(_upgrade, previous)
        if has_legacy_data:
            await connection.execute(
                text("INSERT INTO conversations (id, title) VALUES (:id, 'legacy')"), {"id": old_id}
            )
    if has_legacy_data:
        with pytest.raises(DBAPIError, match="existing conversations"):
            async with pg_engine.begin() as connection:
                await connection.run_sync(_upgrade, current)
        async with pg_engine.connect() as connection:
            assert await connection.scalar(text("SELECT id FROM conversations")) == old_id
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            assert "users" not in tables and "auth_sessions" not in tables
    else:
        async with pg_engine.begin() as connection:
            await connection.run_sync(_upgrade, current)
        async with pg_engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: inspect(sync).get_columns("conversations")
            )
            owner_column = next(column for column in columns if column["name"] == "user_id")
            assert owner_column["nullable"] is False
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            assert "users" in tables and "auth_sessions" in tables
