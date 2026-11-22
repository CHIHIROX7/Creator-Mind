from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.deps import current_identity
from app.api.routes import conversations as conversation_routes
from app.core.csrf import require_csrf
from app.db.session import get_db
from app.main import app
from app.models.conversation import Message
from app.models.conversation_memory import AgentMemory, ConversationSummary
from app.services import conversation_memory as memory_service


def test_extracts_preference_constraint_and_fact() -> None:
    candidates = memory_service.extract_memory_candidates(
        "请记住：我更喜欢先给结论。不要使用夸张标题。我的目标读者是大学生。"
    )

    assert candidates == [
        ("preference", "我更喜欢先给结论"),
        ("constraint", "不要使用夸张标题"),
        ("fact", "我的目标读者是大学生"),
    ]


def test_ignores_regular_conversation() -> None:
    assert memory_service.extract_memory_candidates("帮我写一篇关于量子计算的科普文章") == []


def make_memory(
    user_id: UUID, conversation_id: UUID, message_id: UUID | None = None
) -> AgentMemory:
    now = datetime.now(UTC)
    return AgentMemory(
        id=uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        source_message_id=message_id,
        memory_type="preference",
        content="先给结论，再展开原因。",
        keywords=["结论", "原因"],
        importance=Decimal("0.8"),
        status="active",
        access_count=0,
        last_accessed_at=None,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def test_renders_short_and_long_term_context() -> None:
    now = datetime.now(UTC)
    user_id = uuid4()
    conversation_id = uuid4()
    summary = ConversationSummary(
        id=uuid4(),
        conversation_id=conversation_id,
        summary="讨论量子计算科普文章，读者为大学生。",
        covered_message_id=None,
        message_count=10,
        created_at=now,
        updated_at=now,
    )
    message = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        role="user",
        content="先讲清楚量子比特是什么。",
        created_at=now,
    )
    memory = make_memory(user_id, conversation_id, message.id)

    context = memory_service.render_memory_context(summary, [message], [memory])

    assert "## 对话摘要" in context
    assert "## 短期记忆（最近对话）" in context
    assert "用户: 先讲清楚量子比特是什么。" in context
    assert "## 长期记忆" in context
    assert "[偏好] 先给结论，再展开原因。" in context


@pytest.fixture
def client():
    user_id = uuid4()

    async def override_db():
        yield object()

    async def allow_csrf():
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_identity] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=user_id)
    )
    app.dependency_overrides[require_csrf] = allow_csrf
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    yield client, user_id
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_conversation_memory_endpoint(client, monkeypatch):
    http_client, user_id = client
    conversation_id = uuid4()
    now = datetime.now(UTC)
    message = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        role="user",
        content="请记住：我偏好先给结论。",
        created_at=now,
    )
    memory = make_memory(user_id, conversation_id, message.id)
    memory.content = "我偏好先给结论。"

    async def fake_require(*args, **kwargs):
        return object()

    async def fake_bundle(*args, **kwargs):
        return memory_service.MemoryBundle(None, [message], [memory], "记忆上下文")

    monkeypatch.setattr(conversation_routes, "require_conversation", fake_require)
    monkeypatch.setattr(memory_service, "build_memory_bundle", fake_bundle)

    response = await http_client.get(f"/api/v1/conversations/{conversation_id}/memory")

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == str(conversation_id)
    assert body["short_term_messages"][0]["content"] == "请记住：我偏好先给结论。"
    assert body["long_term_memories"][0]["memory_type"] == "preference"
    assert body["context"] == "记忆上下文"


@pytest.mark.asyncio
async def test_clear_conversation_memory(client, monkeypatch):
    http_client, _ = client
    conversation_id = uuid4()

    async def fake_require(*args, **kwargs):
        return object()

    async def fake_clear(*args, **kwargs):
        return 2

    monkeypatch.setattr(conversation_routes, "require_conversation", fake_require)
    monkeypatch.setattr(memory_service, "clear_conversation_memory", fake_clear)

    response = await http_client.delete(f"/api/v1/conversations/{conversation_id}/memory")

    assert response.status_code == 204