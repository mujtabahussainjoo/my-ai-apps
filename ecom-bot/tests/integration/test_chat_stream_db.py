"""Integration tests for ChatService streaming persistence against the live schema (TASK-036).

Skipped when PostgreSQL is unreachable; runs inside a rolled-back transaction. The agent graph is
replaced with a deterministic stub so only the service/DB behavior is exercised.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.db.repositories import ConversationRepository
from ecommerce_support.schemas import (
    AgentState,
    ChatRequest,
    MessageEndEvent,
    MessageStartEvent,
    TicketRequest,
    TokenEvent,
)
from ecommerce_support.schemas.enums import ConversationStatus, MessageRole
from ecommerce_support.services import ChatService

pytestmark = pytest.mark.integration

_ANSWER = "Your order ships tomorrow."


class _StubAgents:
    async def ainvoke(self, state: AgentState) -> AgentState:
        return state.model_copy(update={"answer": _ANSWER})


class _StubEscalations:
    def build_request(self, state: AgentState) -> TicketRequest:
        raise AssertionError("no escalation expected")


def _service(session: AsyncSession, *, commit=None):  # type: ignore[no-untyped-def]
    return ChatService(
        agents=_StubAgents(),  # type: ignore[arg-type]
        conversations=ConversationRepository(session),
        escalations=_StubEscalations(),  # type: ignore[arg-type]
        commit=commit,  # type: ignore[arg-type]
    )


async def test_stream_persists_answer_and_events(session: AsyncSession) -> None:
    repo = ConversationRepository(session)
    service = _service(session)
    events = [e async for e in service.stream(ChatRequest(message="where is my order?"))]

    assert isinstance(events[0], MessageStartEvent)
    assert isinstance(events[-1], MessageEndEvent)

    tokens = "".join(e.text for e in events if isinstance(e, TokenEvent))
    assert tokens == _ANSWER
    end = events[-1]
    assert end.content == _ANSWER
    assert end.message_id is not None
    assert end.conversation_status is ConversationStatus.IN_PROGRESS

    stored = await repo.get(end.conversation_id)
    assert stored is not None
    assert [m.role for m in stored.messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert stored.messages[-1].content == _ANSWER


async def test_disconnect_persists_partial_state(session: AsyncSession) -> None:
    commits: list[int] = []

    async def commit() -> None:
        commits.append(1)

    repo = ConversationRepository(session)
    service = _service(session, commit=commit)
    stream = service.stream(ChatRequest(message="hello"))
    start = await anext(stream)
    assert isinstance(start, MessageStartEvent)
    assert start.conversation_id is not None

    with pytest.raises(asyncio.CancelledError):
        await stream.athrow(asyncio.CancelledError())

    stored = await repo.get(start.conversation_id)
    assert stored is not None
    assert stored.status is ConversationStatus.ERROR
    assert stored.messages[-1].role is MessageRole.ASSISTANT
    assert commits == [1]
