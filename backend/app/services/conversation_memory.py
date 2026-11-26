"""Short-term and long-term memory for conversation-aware agents."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Message
from app.models.conversation_memory import AgentMemory, ConversationSummary

SUMMARY_BATCH_SIZE = 6
SUMMARY_MIN_MESSAGES = 8
MEMORY_PREFETCH_LIMIT = 200

PREFERENCE_CUES = ("喜欢", "偏好", "倾向", "希望", "习惯", "更喜欢")
CONSTRAINT_CUES = ("不要", "别用", "别写", "必须", "禁止", "请勿", "避免", "务必")
REMEMBER_CUES = ("记住", "请记住", "以后", "每次", "始终")
FACT_PATTERNS = (re.compile(r"我的.{1,30}(是|为|叫)"), re.compile(r"我是.{1,30}"))


class ConversationMemoryNotFoundError(LookupError):
    """Raised when a memory does not belong to the requested conversation."""


@dataclass(frozen=True)
class MemoryBundle:
    summary: ConversationSummary | None
    short_term_messages: list[Message]
    long_term_memories: list[AgentMemory]
    context: str


def extract_memory_candidates(text: str) -> list[tuple[str, str]]:
    """Extract durable user facts from explicit conversational cues.

    This deterministic baseline keeps the MVP usable without an LLM call. The
    function is intentionally isolated so a model-based extractor can replace it
    later without changing persistence or retrieval.
    """
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_sentence in re.split(r"[。！？!?；;\n]+", text):
        sentence = " ".join(raw_sentence.split()).strip()
        if len(sentence) < 4 or len(sentence) > 500:
            continue

        has_remember = any(cue in sentence for cue in REMEMBER_CUES)
        has_preference = any(cue in sentence for cue in PREFERENCE_CUES)
        has_constraint = any(cue in sentence for cue in CONSTRAINT_CUES)
        has_fact = any(pattern.search(sentence) for pattern in FACT_PATTERNS)
        if not any((has_remember, has_preference, has_constraint, has_fact)):
            continue

        content = re.sub(r"^(请)?记住[:：,，\s]*", "", sentence).strip()
        normalized = _normalize(content)
        if len(normalized) < 4 or normalized in seen:
            continue

        if has_constraint:
            memory_type = "constraint"
        elif has_preference:
            memory_type = "preference"
        else:
            memory_type = "fact"
        candidates.append((memory_type, content))
        seen.add(normalized)
        if len(candidates) >= 3:
            break
    return candidates


def extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,4}|[A-Za-z0-9_]{2,}", text.lower())
    return list(dict.fromkeys(tokens))[:12]


async def remember_user_message(
    db: AsyncSession,
    user_id: UUID,
    conversation_id: UUID,
    message: Message,
) -> int:
    """Persist extracted long-term memories and refresh the rolling summary."""
    if message.role != "user":
        return 0

    existing_result = await db.scalars(
        select(AgentMemory)
        .where(AgentMemory.user_id == user_id, AgentMemory.status == "active")
        .order_by(AgentMemory.updated_at.desc())
        .limit(MEMORY_PREFETCH_LIMIT)
    )
    existing_memories = list(existing_result.all())
    written = 0
    now = datetime.now(UTC)

    for memory_type, content in extract_memory_candidates(message.content):
        matching = next(
            (
                memory
                for memory in existing_memories
                if _memory_similarity(memory.content, content) >= 0.75
            ),
            None,
        )
        importance = {
            "preference": Decimal("0.800"),
            "constraint": Decimal("0.850"),
            "fact": Decimal("0.650"),
        }[memory_type]

        if matching is not None:
            matching.conversation_id = conversation_id
            matching.source_message_id = message.id
            matching.memory_type = memory_type
            matching.content = content
            matching.keywords = extract_keywords(content)
            matching.importance = max(matching.importance, importance)
            matching.updated_at = now
            matching.deleted_at = None
            matching.status = "active"
            continue

        memory = AgentMemory(
            user_id=user_id,
            conversation_id=conversation_id,
            source_message_id=message.id,
            memory_type=memory_type,
            content=content,
            keywords=extract_keywords(content),
            importance=importance,
            status="active",
            access_count=0,
        )
        db.add(memory)
        existing_memories.append(memory)
        written += 1

    await db.commit()
    await _refresh_summary_if_needed(db, conversation_id)
    return written


async def load_short_term_messages(
    db: AsyncSession,
    conversation_id: UUID,
    *,
    limit: int = 12,
) -> list[Message]:
    result = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    return list(reversed(result.all()))


async def load_long_term_memories(
    db: AsyncSession,
    user_id: UUID,
    *,
    query: str | None = None,
    limit: int = 8,
) -> list[AgentMemory]:
    result = await db.scalars(
        select(AgentMemory)
        .where(AgentMemory.user_id == user_id, AgentMemory.status == "active")
        .order_by(AgentMemory.updated_at.desc())
        .limit(MEMORY_PREFETCH_LIMIT)
    )
    memories = list(result.all())
    if query and query.strip():
        memories.sort(key=lambda memory: _relevance(memory, query), reverse=True)
    return memories[:limit]


async def build_memory_bundle(
    db: AsyncSession,
    user_id: UUID,
    conversation_id: UUID,
    *,
    query: str | None = None,
    recent_limit: int = 12,
    long_term_limit: int = 8,
) -> MemoryBundle:
    summary = await db.scalar(
        select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
    )
    short_term = await load_short_term_messages(db, conversation_id, limit=recent_limit)
    long_term = await load_long_term_memories(db, user_id, query=query, limit=long_term_limit)
    context = render_memory_context(summary, short_term, long_term)
    return MemoryBundle(summary, short_term, long_term, context)


def render_memory_context(
    summary: ConversationSummary | None,
    messages: list[Message],
    memories: list[AgentMemory],
) -> str:
    sections: list[str] = []
    if summary is not None:
        sections.append(f"## 对话摘要\n{summary.summary.strip()}")

    if messages:
        dialogue_lines = []
        for message in messages[-12:]:
            role = {"user": "用户", "assistant": "助手", "system": "系统"}.get(
                message.role, message.role
            )
            content = " ".join(message.content.split())
            dialogue_lines.append(f"{role}: {content[:600]}")
        sections.append("## 短期记忆（最近对话）\n" + "\n".join(dialogue_lines))

    if memories:
        memory_lines = []
        labels = {"preference": "偏好", "constraint": "约束", "fact": "事实"}
        for memory in memories:
            memory_lines.append(
                f"- [{labels.get(memory.memory_type, memory.memory_type)}] {memory.content}"
            )
        sections.append("## 长期记忆\n" + "\n".join(memory_lines))

    return "\n\n".join(sections)


async def delete_long_term_memory(
    db: AsyncSession,
    user_id: UUID,
    conversation_id: UUID,
    memory_id: UUID,
) -> None:
    memory = await db.scalar(
        select(AgentMemory).where(
            AgentMemory.id == memory_id,
            AgentMemory.user_id == user_id,
            AgentMemory.conversation_id == conversation_id,
            AgentMemory.status == "active",
        )
    )
    if memory is None:
        raise ConversationMemoryNotFoundError
    memory.status = "deleted"
    memory.deleted_at = datetime.now(UTC)
    memory.updated_at = datetime.now(UTC)
    await db.commit()


async def clear_conversation_memory(db: AsyncSession, user_id: UUID, conversation_id: UUID) -> int:
    result = await db.scalars(
        select(AgentMemory).where(
            AgentMemory.user_id == user_id,
            AgentMemory.conversation_id == conversation_id,
            AgentMemory.status == "active",
        )
    )
    memories = list(result.all())
    now = datetime.now(UTC)
    for memory in memories:
        memory.status = "deleted"
        memory.deleted_at = now
        memory.updated_at = now

    summary = await db.scalar(
        select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
    )
    if summary is not None:
        await db.delete(summary)
    await db.commit()
    return len(memories)


async def _refresh_summary_if_needed(db: AsyncSession, conversation_id: UUID) -> None:
    message_count = await db.scalar(
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
    )
    if not message_count or message_count < SUMMARY_MIN_MESSAGES:
        return

    summary = await db.scalar(
        select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id)
    )
    if summary is not None and message_count - summary.message_count < SUMMARY_BATCH_SIZE:
        return

    result = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(40)
    )
    recent_messages = list(reversed(result.all()))
    user_excerpts = [
        " ".join(message.content.split())[:180]
        for message in recent_messages
        if message.role == "user" and message.content.strip()
    ][-10:]
    if not user_excerpts:
        return

    summary_text = "；".join(user_excerpts)[-3000:]
    covered_message_id = recent_messages[-1].id if recent_messages else None
    if summary is None:
        summary = ConversationSummary(
            conversation_id=conversation_id,
            summary=summary_text,
            covered_message_id=covered_message_id,
            message_count=message_count,
        )
        db.add(summary)
    else:
        summary.summary = summary_text
        summary.covered_message_id = covered_message_id
        summary.message_count = message_count
        summary.updated_at = datetime.now(UTC)
    await db.commit()


def _normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower(), flags=re.UNICODE)


def _memory_similarity(left: str, right: str) -> float:
    left_chars = set(_normalize(left))
    right_chars = set(_normalize(right))
    if not left_chars or not right_chars:
        return 0.0
    return len(left_chars & right_chars) / len(left_chars | right_chars)


def _relevance(memory: AgentMemory, query: str) -> float:
    query_chars = set(_normalize(query))
    if not query_chars:
        return 0.0
    content_chars = set(_normalize(memory.content))
    overlap = len(query_chars & content_chars) / len(query_chars)
    keyword_bonus = sum(0.1 for keyword in memory.keywords if keyword in query.lower())
    importance = float(memory.importance)
    return overlap + keyword_bonus + importance * 0.2