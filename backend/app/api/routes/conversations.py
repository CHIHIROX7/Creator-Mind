"""Conversation CRUD and conversation memory restricted to the authenticated owner."""

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentIdentity, DbSession
from app.core.csrf import require_csrf
from app.core.errors import ApiError
from app.models.conversation import Conversation, Message
from app.schemas.conversation import (
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageCreate,
    MessageOut,
)
from app.schemas.conversation_memory import ConversationMemoryOut
from app.services import conversation_memory as memory_service

router = APIRouter(prefix="/conversations", tags=["conversations"])
MemoryQuery = Annotated[str | None, Query(max_length=500)]
MemoryRecentLimit = Annotated[int, Query(ge=1, le=50)]
MemoryLongTermLimit = Annotated[int, Query(ge=1, le=30)]

logger = logging.getLogger(__name__)


async def require_conversation(
    db: AsyncSession, conversation_id: UUID, user_id: UUID
) -> Conversation:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conversation is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "对话不存在")
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(db: DbSession, identity: CurrentIdentity) -> list[Conversation]:
    result = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == identity.user.id)
        .order_by(
            Conversation.updated_at.desc(), Conversation.created_at.desc(), Conversation.id.desc()
        )
        .limit(200)
    )
    return list(result.all())


@router.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_conversation(
    payload: ConversationCreate, db: DbSession, identity: CurrentIdentity
) -> Conversation:
    title = payload.title.strip()
    if not title:
        raise ApiError(422, "VALIDATION_ERROR", "标题不能全为空格")
    conversation = Conversation(title=title, user_id=identity.user.id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    conversation_id: UUID, db: DbSession, identity: CurrentIdentity
) -> Conversation:
    return await require_conversation(db, conversation_id, identity.user.id)


@router.patch(
    "/{conversation_id}", response_model=ConversationOut, dependencies=[Depends(require_csrf)]
)
async def rename_conversation(
    conversation_id: UUID, payload: ConversationUpdate, db: DbSession, identity: CurrentIdentity
) -> Conversation:
    conversation = await require_conversation(db, conversation_id, identity.user.id)
    title = payload.title.strip()
    if not title:
        raise ApiError(422, "VALIDATION_ERROR", "标题不能全为空格")
    conversation.title = title
    conversation.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_conversation(
    conversation_id: UUID, db: DbSession, identity: CurrentIdentity
) -> Response:
    conversation = await require_conversation(db, conversation_id, identity.user.id)
    await db.delete(conversation)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: UUID, db: DbSession, identity: CurrentIdentity
) -> list[Message]:
    await require_conversation(db, conversation_id, identity.user.id)
    result = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(1000)
    )
    return list(result.all())


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_message(
    conversation_id: UUID, payload: MessageCreate, db: DbSession, identity: CurrentIdentity
) -> Message:
    conversation = await require_conversation(db, conversation_id, identity.user.id)
    content = payload.content.strip()
    if not content:
        raise ApiError(422, "VALIDATION_ERROR", "消息不能为空")
    message = Message(conversation_id=conversation_id, role=payload.role, content=content)
    db.add(message)
    conversation.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(message)
    message_id = message.id

    if payload.role == "user":
        try:
            await memory_service.remember_user_message(
                db, identity.user.id, conversation_id, message
            )
        except Exception:
            await db.rollback()
            logger.exception(
                "Conversation memory update failed: user_id=%s conversation_id=%s message_id=%s",
                identity.user.id,
                conversation_id,
                message_id,
            )
            message = await db.get(Message, message_id)
            if message is None:
                raise ApiError(
                    500, "MEMORY_UPDATE_FAILED", "消息已保存，但记忆更新失败"
                ) from None
    return message


@router.get("/{conversation_id}/memory", response_model=ConversationMemoryOut)
async def get_conversation_memory(
    conversation_id: UUID,
    db: DbSession,
    identity: CurrentIdentity,
    query: MemoryQuery = None,
    recent_limit: MemoryRecentLimit = 12,
    long_term_limit: MemoryLongTermLimit = 8,
) -> ConversationMemoryOut:
    await require_conversation(db, conversation_id, identity.user.id)
    bundle = await memory_service.build_memory_bundle(
        db,
        identity.user.id,
        conversation_id,
        query=query,
        recent_limit=recent_limit,
        long_term_limit=long_term_limit,
    )
    return ConversationMemoryOut(
        conversation_id=conversation_id,
        summary=bundle.summary,
        short_term_messages=bundle.short_term_messages,
        long_term_memories=bundle.long_term_memories,
        context=bundle.context,
    )


@router.delete(
    "/{conversation_id}/memory/long-term/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_long_term_memory(
    conversation_id: UUID,
    memory_id: UUID,
    db: DbSession,
    identity: CurrentIdentity,
) -> Response:
    await require_conversation(db, conversation_id, identity.user.id)
    try:
        await memory_service.delete_long_term_memory(
            db, identity.user.id, conversation_id, memory_id
        )
    except memory_service.ConversationMemoryNotFoundError as exc:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "长期记忆不存在") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{conversation_id}/memory",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def clear_conversation_memory(
    conversation_id: UUID, db: DbSession, identity: CurrentIdentity
) -> Response:
    await require_conversation(db, conversation_id, identity.user.id)
    await memory_service.clear_conversation_memory(db, identity.user.id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)