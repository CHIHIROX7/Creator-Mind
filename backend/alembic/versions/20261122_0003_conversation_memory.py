"""Create conversation summaries and long-term agent memories.

Revision ID: 20261122_0003
Revises: 20261120_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261122_0003"
down_revision: str | Sequence[str] | None = "20261120_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("covered_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("conversation_id", name="uq_conversation_summaries_conversation"),
    )
    op.create_index("ix_conversation_summaries_updated", "conversation_summaries", ["updated_at"])

    op.create_table(
        "agent_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("memory_type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(), nullable=False),
        sa.Column("importance", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("access_count", sa.Integer(), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "memory_type IN ('preference', 'constraint', 'fact')",
            name="ck_agent_memories_type",
        ),
        sa.CheckConstraint("status IN ('active', 'deleted')", name="ck_agent_memories_status"),
        sa.CheckConstraint(
            "importance >= 0 AND importance <= 1", name="ck_agent_memories_importance"
        ),
    )
    op.create_index("ix_agent_memories_status_updated", "agent_memories", ["status", "updated_at"])
    op.create_index(
        "ix_agent_memories_source_conversation", "agent_memories", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_memories_source_conversation", table_name="agent_memories")
    op.drop_index("ix_agent_memories_status_updated", table_name="agent_memories")
    op.drop_table("agent_memories")
    op.drop_index("ix_conversation_summaries_updated", table_name="conversation_summaries")
    op.drop_table("conversation_summaries")