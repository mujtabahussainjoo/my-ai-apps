"""Integration tests for TicketService against the live schema (TASK-034).

Skipped when PostgreSQL is unreachable; runs inside a rolled-back transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.exceptions import TicketCreationError
from ecommerce_support.db.repositories import (
    AuditEventRepository,
    ConversationRepository,
    TicketRepository,
)
from ecommerce_support.integrations import MockTicketingAdapter
from ecommerce_support.schemas import TicketRequest
from ecommerce_support.schemas.enums import ConversationStatus, TicketStatus
from ecommerce_support.services import TicketService

pytestmark = pytest.mark.integration


async def _conversation(session: AsyncSession):
    return await ConversationRepository(session).create(
        user_id=None, status=ConversationStatus.IN_PROGRESS
    )


def _request(conversation_id: str, **overrides: object) -> TicketRequest:
    data: dict[str, object] = {
        "conversation_id": conversation_id,
        "summary": "Order never arrived",
    }
    data.update(overrides)
    return TicketRequest(**data)


async def test_escalate_persists_and_dedupes(session: AsyncSession) -> None:
    conversation = await _conversation(session)
    adapter = MockTicketingAdapter()
    service = TicketService.from_session(session, adapter)

    first = await service.escalate(_request(conversation.id))
    assert first.created is True
    assert first.ticket.status is TicketStatus.CREATED
    assert first.ticket.external_id is not None

    second = await service.escalate(_request(conversation.id))
    assert second.created is False
    assert second.ticket.id == first.ticket.id
    assert len(adapter.calls) == 1

    stored = await ConversationRepository(session).get(conversation.id)
    assert stored is not None and stored.status is ConversationStatus.TICKET_CREATED

    events = await AuditEventRepository(session).list_for_conversation(conversation.id)
    assert [e.event_type for e in events] == ["ticket.created"]


async def test_explicit_idempotency_key_is_unique(session: AsyncSession) -> None:
    conversation = await _conversation(session)
    adapter = MockTicketingAdapter()
    service = TicketService.from_session(session, adapter)

    first = await service.escalate(_request(conversation.id, idempotency_key="dup-1"))
    second = await service.escalate(_request(conversation.id, idempotency_key="dup-1"))
    assert second.ticket.id == first.ticket.id
    assert len(adapter.calls) == 1

    by_key = await TicketRepository(session).get_by_idempotency_key("dup-1")
    assert by_key is not None and by_key.id == first.ticket.id


async def test_failure_then_retry_is_truthful(session: AsyncSession) -> None:
    conversation = await _conversation(session)
    adapter = MockTicketingAdapter(fail_next=1)
    service = TicketService.from_session(session, adapter)

    with pytest.raises(TicketCreationError):
        await service.escalate(_request(conversation.id))

    stored = await ConversationRepository(session).get(conversation.id)
    assert stored is not None and stored.status is ConversationStatus.TICKET_CREATION_FAILED

    failed_rows = await TicketRepository(session).list_by_conversation(conversation.id)
    assert [t.status for t in failed_rows] == [TicketStatus.FAILED]
    assert failed_rows[0].idempotency_key is None
    failed = await TicketRepository(session).find_active_by_conversation(conversation.id)
    assert failed is None  # failed attempts do not count as an active ticket

    result = await service.escalate(_request(conversation.id))
    assert result.created is True
    assert len(adapter.calls) == 2

    active = await TicketRepository(session).find_active_by_conversation(conversation.id)
    assert active is not None and active.status is TicketStatus.CREATED
    stored = await ConversationRepository(session).get(conversation.id)
    assert stored is not None and stored.status is ConversationStatus.TICKET_CREATED

    events = await AuditEventRepository(session).list_for_conversation(conversation.id)
    assert [e.event_type for e in events] == ["ticket.creation_failed", "ticket.created"]


async def test_failure_rolls_under_repeated_attempts(session: AsyncSession) -> None:
    conversation = await _conversation(session)
    adapter = MockTicketingAdapter(always_fail=True)
    service = TicketService.from_session(session, adapter)
    with pytest.raises(TicketCreationError):
        await service.escalate(_request(conversation.id))
    with pytest.raises(TicketCreationError):
        await service.escalate(_request(conversation.id))
    assert len(adapter.calls) == 2
    stored = await ConversationRepository(session).get(conversation.id)
    assert stored is not None and stored.status is ConversationStatus.TICKET_CREATION_FAILED


async def test_acc_005_retry_then_reference_is_returned(session: AsyncSession) -> None:
    """ACC-005: bounded retry → ticket created with a reference the customer can use."""
    conversation = await _conversation(session)
    adapter = MockTicketingAdapter(fail_next=1)
    service = TicketService.from_session(session, adapter)

    with pytest.raises(TicketCreationError):
        await service.escalate(_request(conversation.id))

    result = await service.escalate(_request(conversation.id))
    assert result.created is True
    assert result.ticket.external_id
    assert result.ticket.external_id in result.message

    stored = await ConversationRepository(session).get(conversation.id)
    assert stored is not None and stored.status is ConversationStatus.TICKET_CREATED


async def test_acc_006_failure_is_truthful_and_retry_available(session: AsyncSession) -> None:
    """ACC-006: failure is truthful, escalation preserved, and a retry can still succeed."""
    conversation = await _conversation(session)
    adapter = MockTicketingAdapter(always_fail=True)
    service = TicketService.from_session(session, adapter)

    with pytest.raises(TicketCreationError) as excinfo:
        await service.escalate(_request(conversation.id))
    assert "secret" not in excinfo.value.message  # truthful, no internal material

    failed = await ConversationRepository(session).get(conversation.id)
    assert failed is not None and failed.status is ConversationStatus.TICKET_CREATION_FAILED

    adapter.recover()  # provider recovers; a retry must succeed
    result = await service.escalate(_request(conversation.id))
    assert result.created is True
    recovered = await ConversationRepository(session).get(conversation.id)
    assert recovered is not None and recovered.status is ConversationStatus.TICKET_CREATED
