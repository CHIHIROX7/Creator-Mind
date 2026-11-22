"""API contracts for short-term and long-term conversation memory."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.conversation import MessageOut

MemoryType = Literal["preference", "constraint", "fact"]


class ConversationSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    summary: str
    covered_message_id: UUID | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class AgentMemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    conversation_id: UUID | None
    source_message_id: UUID | None
    memory_type: MemoryType
    content: str
    keywords: list[str]
    importance: float
    status: Literal["active", "deleted"]
    access_count: int
    last_accessed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ConversationMemoryOut(BaseModel):
    conversation_id: UUID
    summary: ConversationSummaryOut | None
    short_term_messages: list[MessageOut]
    long_term_memories: list[AgentMemoryOut]
    context: str