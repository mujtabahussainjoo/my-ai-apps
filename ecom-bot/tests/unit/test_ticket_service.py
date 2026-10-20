"""Unit tests for TicketService: lifecycle, idempotency, retry safety, failure (TASK-034).

Uses the real ``MockTicketingAdapter`` (deterministic) with in-memory repository fakes so the
service's business rules are exercised without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ecommerce_support.core.exceptions import (
    InvalidStateTransition,
    NotFoundError,
    TicketCreationError,
)
from ecommerce_support.integrations import MockTicketingAdapter
from ecommerce_support.schemas import (
    AuditEventCreate,
    Conversation,
    Ticket,
    TicketRequest,
)
from ecommerce_support.schemas.enums import ConversationStatus, TicketStatus
from ecommerce_support.services import TicketService

_NOW = datetime(2026, 10, 10, tzinfo=UTC)


def _conversation(status: ConversationStatus = ConversationStatus.IN_PROGRESS) -> Conversation:
    return Conversation(
        id="conv-1", user_id="cust-1", status=status, created_at=_NOW, updated_at=_NOW
    )


def _request(**overrides: object) -> TicketRequest:
    data: dict[str, object] = {"conversation_id": "conv-1", "summary": "Order never arrived"}
    data.update(overrides)
    return TicketRequest(**data)


class FakeConversations:
    def __init__(self, conversation: Conversation | None) -> None:
        self.conversation = conversation
        self.status_updates: list[ConversationStatus] = []

    async def get(self, conversation_id: str) -> Conversation | None:
        if self.conversation and self.conversation.id == conversation_id:
            return self.conversation
        return None

    async def update_status(
        self, conversation_id: str, status: ConversationStatus, **_kwargs: object
    ) -> Conversation:
        assert self.conversation is not None
        self.conversation = self.conversation.model_copy(update={"status": status})
        self.status_updates.append(status)
        return self.conversation


class FakeTickets:
    def __init__(self) -> None:
        self.rows: list[Ticket] = []
        self._seq = 0

    async def get(self, ticket_id: str) -> Ticket | None:
        return next((t for t in self.rows if t.id == ticket_id), None)

    async def get_by_idempotency_key(self, key: str) -> Ticket | None:
        return next((t for t in self.rows if t.idempotency_key == key), None)

    async def list_by_conversation(self, conversation_id: str) -> list[Ticket]:
        return [t for t in self.rows if t.conversation_id == conversation_id]

    async def find_active_by_conversation(self, conversation_id: str) -> Ticket | None:
        active = [
            t
            for t in self.rows
            if t.conversation_id == conversation_id and t.status is not TicketStatus.FAILED
        ]
        return active[-1] if active else None

    async def create_idempotent(
        self,
        request: TicketRequest,
        *,
        provider: object,
        status: TicketStatus,
        external_id: str | None = None,
        url: str | None = None,
    ) -> tuple[Ticket, bool]:
        if request.idempotency_key is not None:
            existing = await self.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                return existing, False
        self._seq += 1
        row = Ticket(
            id=f"tkt_{self._seq}",
            conversation_id=request.conversation_id,
            provider=provider,  # type: ignore[arg-type]
            status=status,
            summary=request.summary,
            priority=request.priority,
            external_id=external_id,
            url=url,
            idempotency_key=request.idempotency_key,
            created_at=_NOW,
        )
        self.rows.append(row)
        return row, True

    async def create_failed(
        self, request: TicketRequest, *, provider: object, error_code: str
    ) -> Ticket:
        self._seq += 1
        row = Ticket(
            id=f"tkt_{self._seq}",
            conversation_id=request.conversation_id,
            provider=provider,  # type: ignore[arg-type]
            status=TicketStatus.FAILED,
            summary=request.summary,
            priority=request.priority,
            external_id=None,
            url=None,
            idempotency_key=None,
            created_at=_NOW,
        )
        self.rows.append(row)
        return row

    async def update(
        self,
        ticket_id: str,
        *,
        status: TicketStatus | None = None,
        external_id: str | None = None,
        url: str | None = None,
        priority: object = None,
    ) -> Ticket | None:
        row = await self.get(ticket_id)
        if row is None:
            return None
        if status is not None:
            row.status = status
        if external_id is not None:
            row.external_id = external_id
        if url is not None:
            row.url = url
        return row


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEventCreate] = []

    async def record(self, event: AuditEventCreate) -> AuditEventCreate:
        self.events.append(event)
        return event


def _service(
    conversation: Conversation | None = None,
    *,
    adapter: MockTicketingAdapter | None = None,
) -> tuple[TicketService, FakeTickets, FakeConversations, FakeAudit, MockTicketingAdapter]:
    tickets = FakeTickets()
    conversations = FakeConversations(conversation)
    audit = FakeAudit()
    ticketing = adapter or MockTicketingAdapter()
    service = TicketService(
        tickets=tickets,  # type: ignore[arg-type]
        conversations=conversations,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        adapter=ticketing,
    )
    return service, tickets, conversations, audit, ticketing


async def test_success_creates_ticket_and_transitions() -> None:
    service, tickets, conversations, audit, adapter = _service(_conversation())
    result = await service.escalate(_request())
    assert result.created is True
    assert result.ticket.status is TicketStatus.CREATED
    assert result.ticket.external_id in result.message
    assert conversations.conversation is not None
    assert conversations.conversation.status is ConversationStatus.TICKET_CREATED
    assert conversations.status_updates == [
        ConversationStatus.ESCALATION_PENDING,
        ConversationStatus.TICKET_CREATED,
    ]
    assert len(adapter.calls) == 1
    assert [e.event_type for e in audit.events] == ["ticket.created"]
    assert len(tickets.rows) == 1


async def test_default_idempotency_key_is_derived() -> None:
    service, _, _, _, adapter = _service(_conversation())
    await service.escalate(_request())
    assert adapter.calls[0].idempotency_key == "escalation:conv-1"


async def test_repeat_is_reused_without_second_call() -> None:
    service, tickets, _, _, adapter = _service(_conversation())
    first = await service.escalate(_request())
    second = await service.escalate(_request())
    assert second.created is False
    assert second.ticket.id == first.ticket.id
    assert len(adapter.calls) == 1
    assert len(tickets.rows) == 1


async def test_explicit_key_is_preserved_and_reused() -> None:
    service, _, _, _, adapter = _service(_conversation())
    first = await service.escalate(_request(idempotency_key="fixed-key"))
    assert adapter.calls[0].idempotency_key == "fixed-key"
    second = await service.escalate(_request(idempotency_key="fixed-key"))
    assert second.created is False
    assert second.ticket.id == first.ticket.id
    assert len(adapter.calls) == 1


async def test_failure_is_truthful_and_preserves_escalation() -> None:
    adapter = MockTicketingAdapter(always_fail=True)
    service, tickets, conversations, audit, _ = _service(_conversation(), adapter=adapter)
    with pytest.raises(TicketCreationError):
        await service.escalate(_request())
    assert conversations.conversation is not None
    assert conversations.conversation.status is ConversationStatus.TICKET_CREATION_FAILED
    assert [t.status for t in tickets.rows] == [TicketStatus.FAILED]
    assert tickets.rows[0].idempotency_key is None  # key not consumed → retry possible
    assert [e.event_type for e in audit.events] == ["ticket.creation_failed"]


async def test_retry_after_failure_succeeds() -> None:
    adapter = MockTicketingAdapter(fail_next=1)
    service, tickets, conversations, audit, _ = _service(_conversation(), adapter=adapter)
    with pytest.raises(TicketCreationError):
        await service.escalate(_request())
    result = await service.escalate(_request())
    assert result.created is True
    assert conversations.conversation is not None
    assert conversations.conversation.status is ConversationStatus.TICKET_CREATED
    assert len(adapter.calls) == 2
    assert [t.status for t in tickets.rows] == [TicketStatus.FAILED, TicketStatus.CREATED]
    assert [e.event_type for e in audit.events] == ["ticket.creation_failed", "ticket.created"]


async def test_illegal_start_state_raises_without_calling_provider() -> None:
    service, _, _, _, adapter = _service(_conversation(ConversationStatus.OPEN))
    with pytest.raises(InvalidStateTransition):
        await service.escalate(_request())
    assert adapter.calls == []


async def test_missing_conversation_raises_not_found() -> None:
    service, _, _, _, adapter = _service(None)
    with pytest.raises(NotFoundError):
        await service.escalate(_request())
    assert adapter.calls == []


async def test_refresh_status_updates_from_provider() -> None:
    service, _, _, _, adapter = _service(_conversation())
    result = await service.escalate(_request())
    external_id = result.ticket.external_id
    assert external_id is not None
    adapter.tickets[external_id].status = TicketStatus.RESOLVED
    refreshed = await service.refresh_status(result.ticket.id)
    assert refreshed is not None
    assert refreshed.status is TicketStatus.RESOLVED


async def test_refresh_status_without_external_id_is_noop() -> None:
    service, tickets, _, _, _ = _service(_conversation())
    tickets.rows.append(
        Ticket(
            id="tkt_local",
            conversation_id="conv-1",
            provider=MockTicketingAdapter.provider,
            status=TicketStatus.PENDING,
            summary="x",
            created_at=_NOW,
        )
    )
    refreshed = await service.refresh_status("tkt_local")
    assert refreshed is not None
    assert refreshed.status is TicketStatus.PENDING


async def test_list_for_conversation_delegates() -> None:
    service, _, _, _, _ = _service(_conversation())
    await service.escalate(_request())
    assert len(await service.list_for_conversation("conv-1")) == 1
    assert await service.get("missing") is None
