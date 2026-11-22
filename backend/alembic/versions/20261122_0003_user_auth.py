"""Add identity ownership and authentication sessions.

Revision ID: 20261122_0003
Revises: 20261120_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261122_0003"
down_revision: str | Sequence[str] | None = "20261120_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("LOCK TABLE conversations IN ACCESS EXCLUSIVE MODE")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM conversations LIMIT 1) THEN
                RAISE EXCEPTION 'User-auth migration refused: existing conversations require '
                    'an explicitly reviewed ownership migration. No data was deleted.';
            END IF;
        END $$;
        """
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("auth_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("username"),
        sa.CheckConstraint("auth_version >= 0", name="ck_users_auth_version"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("auth_version >= 0", name="ck_auth_sessions_auth_version"),
    )
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.add_column(
        "conversations", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False)
    )
    op.create_foreign_key(
        "fk_conversations_user_id_users", "conversations", "users",
        ["user_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index(
        "ix_conversations_user_time", "conversations",
        ["user_id", "updated_at", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_user_time", table_name="conversations")
    op.drop_constraint("fk_conversations_user_id_users", "conversations", type_="foreignkey")
    op.drop_column("conversations", "user_id")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")
