"""Integration tests for conversation history + message/tool persistence (TASK-037).

Skipped when PostgreSQL is unreachable; runs inside a rolled-back transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.db.repositories import ConversationRepository, ToolExecutionRepository
from ecommerce_support.schemas import AgentState, ChatRequest, PageParams, ToolExecution
from ecommerce_support.schemas.enums import ConversationStatus, MessageRole, ToolCallStatus
from ecommerce_support.services import ChatService
from ecommerce_support.services.conversations import ConversationService

pytestmark = pytest.mark.integration


class _StubAgents:
    def __init__(self, executions: list[ToolExecution]) -> None:
        self._executions = executions

    async def ainvoke(self, state: AgentState) -> AgentState:
        return state.model_copy(update={"answer": "Handled.", "tool_executions": self._executions})


class _StubEscalations:
    def build_request(self, state: AgentState):  # type: ignore[no-untyped-def]
        raise AssertionError("no escalation expected")


async def _seed_repo_activity(session: AsyncSession) -> tuple[str, str]:
    conversations = ConversationRepository(session)
    conversation = await conversations.create(status=ConversationStatus.IN_PROGRESS)
    await conversations.append_message(
        conversation.id, role=MessageRole.USER, content="where is my order?"
    )
    assistant = await conversations.append_message(
        conversation.id, role=MessageRole.ASSISTANT, content="Let me check."
    )
    tools = ToolExecutionRepository(session)
    await tools.record(
        conversation_id=conversation.id,
        message_id=assistant.id,
        tool_name="order_lookup",
        call_id="c1",
        status=ToolCallStatus.ERROR,
        summary="provider timeout",
    )
    await tools.record(
        conversation_id=conversation.id,
        message_id=assistant.id,
        tool_name="order_lookup",
        call_id="c2",
        status=ToolCallStatus.OK,
        summary="found order",
    )
    return conversation.id, assistant.id


async def test_list_messages_paginates_oldest_first(session: AsyncSession) -> None:
    conversation_id, _ = await _seed_repo_activity(session)
    repo = ConversationRepository(session)

    first_page, total = await repo.list_messages(conversation_id, limit=1, offset=0)
    assert total == 2
    assert len(first_page) == 1
    assert first_page[0].role is MessageRole.USER

    second_page, _ = await repo.list_messages(conversation_id, limit=1, offset=1)
    assert second_page[0].role is MessageRole.ASSISTANT


async def test_history_includes_tool_executions_including_failures(
    session: AsyncSession,
) -> None:
    conversation_id, assistant_id = await _seed_repo_activity(session)
    service = ConversationService(ConversationRepository(session), ToolExecutionRepository(session))

    page = await service.list_messages(
        conversation_id, user_id=None, params=PageParams(limit=10, offset=0)
    )
    assert page.total == 2
    assistant = page.items[-1]
    assert assistant.id == assistant_id
    assert [t.tool_name for t in assistant.tool_executions] == ["order_lookup", "order_lookup"]
    # A failed tool call is retained in history (FR-009 — persistence after tool failures).
    assert [t.status for t in assistant.tool_executions] == [
        ToolCallStatus.ERROR,
        ToolCallStatus.OK,
    ]


async def test_get_enriches_conversation_messages(session: AsyncSession) -> None:
    conversation_id, _ = await _seed_repo_activity(session)
    service = ConversationService(ConversationRepository(session), ToolExecutionRepository(session))
    conversation = await service.get(conversation_id, user_id=None)
    assert conversation.messages[0].tool_executions == []
    assert len(conversation.messages[-1].tool_executions) == 2


async def test_history_unknown_conversation_raises(session: AsyncSession) -> None:
    service = ConversationService(ConversationRepository(session), ToolExecutionRepository(session))
    with pytest.raises(NotFoundError):
        await service.list_messages("conv_missing", user_id=None)


async def test_chat_turn_persists_tool_executions_to_history(session: AsyncSession) -> None:
    agent = _StubAgents(
        [
            ToolExecution(
                call_id="c1",
                tool_name="order_lookup",
                status=ToolCallStatus.ERROR,
                summary="provider timeout",
            ),
            ToolExecution(call_id="c2", tool_name="policy_search", status=ToolCallStatus.OK),
        ]
    )
    chat = ChatService(
        agents=agent,  # type: ignore[arg-type]
        conversations=ConversationRepository(session),
        escalations=_StubEscalations(),  # type: ignore[arg-type]
        tool_executions=ToolExecutionRepository(session),
    )
    response = await chat.chat(ChatRequest(message="where is my order?"))

    history = ConversationService(ConversationRepository(session), ToolExecutionRepository(session))
    page = await history.list_messages(response.conversation_id, user_id=None)
    assistant = page.items[-1]
    assert assistant.id == response.message.id
    assert [t.tool_name for t in assistant.tool_executions] == ["order_lookup", "policy_search"]
    assert assistant.tool_executions[0].status is ToolCallStatus.ERROR
