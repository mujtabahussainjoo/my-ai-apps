"""Ticket escalation use-case: lifecycle, idempotency, retry safety, failure handling (FR-043/044).

Plain Python (no web/graph imports). Business rules that keep escalation honest live here:

- A conversation is moved through the FR-047 state machine (``ESCALATION_PENDING`` →
  ``TICKET_CREATED``), and only after the adapter **confirms** a ticket (FR-044).
- Creation is idempotent: a repeat with the same ``idempotency_key`` or an existing non-failed
  ticket for the conversation returns that ticket without calling the provider again (FR-043).
- On failure the conversation moves to ``TICKET_CREATION_FAILED`` (escalation preserved), a
  failed-attempt row is recorded **without** consuming the idempotency key, and the error is
  re-raised so the caller can tell the customer the truth and offer a retry (ACC-006).

Repositories only ``flush``; committing is the caller's/transport's responsibility.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.exceptions import (
    InvalidStateTransition,
    NotFoundError,
    TicketCreationError,
)
from ecommerce_support.core.metrics import COUNTER_ESCALATIONS, get_metrics
from ecommerce_support.db.repositories import (
    AuditEventRepository,
    ConversationRepository,
    TicketRepository,
)
from ecommerce_support.integrations import TicketingAdapter
from ecommerce_support.schemas import (
    AuditEventCreate,
    Conversation,
    Ticket,
    TicketEscalationResult,
    TicketRequest,
)
from ecommerce_support.schemas.enums import ConversationStatus, TicketStatus
from ecommerce_support.workflows.lifecycle import transition as transition_status

TICKET_CREATED_EVENT = "ticket.created"
TICKET_CREATION_FAILED_EVENT = "ticket.creation_failed"

_REUSED_MESSAGE = "An existing ticket already covers this issue."


class TicketService:
    """Creates and tracks escalation tickets against a :class:`TicketingAdapter`."""

    def __init__(
        self,
        *,
        tickets: TicketRepository,
        conversations: ConversationRepository,
        audit: AuditEventRepository,
        adapter: TicketingAdapter,
        default_idempotency_prefix: str = "escalation",
    ) -> None:
        self._tickets = tickets
        self._conversations = conversations
        self._audit = audit
        self._adapter = adapter
        self._idempotency_prefix = default_idempotency_prefix

    @classmethod
    def from_session(
        cls, session: AsyncSession, adapter: TicketingAdapter, **kwargs: str
    ) -> TicketService:
        """Build the service from a DB session and the configured ticketing adapter."""
        return cls(
            tickets=TicketRepository(session),
            conversations=ConversationRepository(session),
            audit=AuditEventRepository(session),
            adapter=adapter,
            **kwargs,
        )

    async def escalate(
        self,
        request: TicketRequest,
        *,
        actor_id: str | None = None,
    ) -> TicketEscalationResult:
        """Create (or idempotently reuse) an escalation ticket for ``request``.

        Raises :class:`NotFoundError` if the conversation does not exist and
        :class:`TicketCreationError` if the provider does not confirm creation. In the failure case
        the conversation is left in ``TICKET_CREATION_FAILED`` so the escalation is preserved and a
        retry is possible.
        """
        conversation = await self._conversations.get(request.conversation_id)
        if conversation is None:
            raise NotFoundError(
                f"conversation {request.conversation_id} not found",
                details={"conversation_id": request.conversation_id},
            )
        request = self._with_idempotency_key(request)

        existing = await self._find_existing(request)
        if existing is not None:
            get_metrics().increment(COUNTER_ESCALATIONS, result="reused")
            await self._mark_created(conversation, tolerate_illegal=True)
            return TicketEscalationResult(ticket=existing, created=False, message=_REUSED_MESSAGE)

        await self._ensure_escalation_pending(conversation)
        try:
            external = await self._adapter.create_ticket(request)
        except TicketCreationError as exc:
            get_metrics().increment(COUNTER_ESCALATIONS, result="failed")
            await self._tickets.create_failed(
                request, provider=self._adapter.provider, error_code=exc.code
            )
            await self._conversations.update_status(
                conversation.id, ConversationStatus.TICKET_CREATION_FAILED
            )
            await self._audit.record(
                AuditEventCreate(
                    event_type=TICKET_CREATION_FAILED_EVENT,
                    actor_id=actor_id,
                    resource_type="ticket",
                    conversation_id=conversation.id,
                    detail={"provider": self._adapter.provider.value, "error_code": exc.code},
                )
            )
            raise

        ticket, created = await self._tickets.create_idempotent(
            request,
            provider=external.provider,
            status=TicketStatus.CREATED,
            external_id=external.external_id,
            url=external.url,
        )
        get_metrics().increment(COUNTER_ESCALATIONS, result="created")
        await self._conversations.update_status(conversation.id, ConversationStatus.TICKET_CREATED)
        await self._audit.record(
            AuditEventCreate(
                event_type=TICKET_CREATED_EVENT,
                actor_id=actor_id,
                resource_type="ticket",
                resource_id=ticket.id,
                conversation_id=conversation.id,
                detail={
                    "provider": ticket.provider.value,
                    "external_id": ticket.external_id,
                    "created": created,
                },
            )
        )
        return TicketEscalationResult(
            ticket=ticket, created=created, message=_created_message(ticket)
        )

    async def get(self, ticket_id: str) -> Ticket | None:
        """Return a persisted ticket by internal id."""
        return await self._tickets.get(ticket_id)

    async def list_for_conversation(self, conversation_id: str) -> list[Ticket]:
        """Return all tickets recorded for a conversation."""
        return await self._tickets.list_by_conversation(conversation_id)

    async def refresh_status(self, ticket_id: str) -> Ticket | None:
        """Re-read a ticket's status from the provider (FR-053), updating the local record."""
        ticket = await self._tickets.get(ticket_id)
        if ticket is None or ticket.external_id is None:
            return ticket
        external = await self._adapter.get_status(ticket.external_id)
        if external is None:
            return ticket
        updated = await self._tickets.update(
            ticket_id,
            status=external.status,
            external_id=external.external_id,
            url=external.url,
        )
        return updated if updated is not None else ticket

    def _with_idempotency_key(self, request: TicketRequest) -> TicketRequest:
        if request.idempotency_key is not None:
            return request
        key = f"{self._idempotency_prefix}:{request.conversation_id}"
        return request.model_copy(update={"idempotency_key": key})

    async def _find_existing(self, request: TicketRequest) -> Ticket | None:
        if request.idempotency_key is not None:
            existing = await self._tickets.get_by_idempotency_key(request.idempotency_key)
            if existing is not None and existing.status is not TicketStatus.FAILED:
                return existing
        return await self._tickets.find_active_by_conversation(request.conversation_id)

    async def _ensure_escalation_pending(self, conversation: Conversation) -> None:
        if conversation.status is ConversationStatus.ESCALATION_PENDING:
            return
        target = transition_status(conversation.status, ConversationStatus.ESCALATION_PENDING)
        await self._conversations.update_status(conversation.id, target)

    async def _mark_created(
        self, conversation: Conversation, *, tolerate_illegal: bool = False
    ) -> None:
        if conversation.status is ConversationStatus.TICKET_CREATED:
            return
        try:
            await self._ensure_escalation_pending(conversation)
        except InvalidStateTransition:
            if not tolerate_illegal:
                raise
            return
        await self._conversations.update_status(conversation.id, ConversationStatus.TICKET_CREATED)


def _created_message(ticket: Ticket) -> str:
    reference = ticket.external_id or ticket.id
    return f"Ticket {reference} has been created and our team will follow up."


__all__ = ["TICKET_CREATED_EVENT", "TICKET_CREATION_FAILED_EVENT", "TicketService"]
