"""Ticket endpoints (FR-053): query persisted tickets and refresh their provider status.

Ticket creation happens inside the chat/escalation flow; these endpoints expose the recorded
tickets for a conversation and let a caller re-read the provider's current status. Access is
ownership-scoped: the caller must own the ticket's conversation (SEC-002).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ecommerce_support.api.dependencies import (
    get_conversation_service,
    get_ticket_service,
    get_user_id,
)
from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.schemas import Ticket
from ecommerce_support.services import TicketService
from ecommerce_support.services.conversations import ConversationService

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])


@router.get(
    "",
    response_model=list[Ticket],
    summary="List tickets for a conversation",
    description="Return every ticket recorded against a conversation you own (FR-053).",
)
async def list_tickets(
    conversation_id: str = Query(min_length=1, max_length=64),
    user_id: str | None = Depends(get_user_id),
    service: TicketService = Depends(get_ticket_service),
    conversations: ConversationService = Depends(get_conversation_service),
) -> list[Ticket]:
    await conversations.assert_access(conversation_id, user_id=user_id)
    return await service.list_for_conversation(conversation_id)


@router.get(
    "/{ticket_id}",
    response_model=Ticket,
    summary="Get a ticket",
    description="Return a persisted ticket by its internal id (owner only; FR-053).",
)
async def get_ticket(
    ticket_id: str,
    user_id: str | None = Depends(get_user_id),
    service: TicketService = Depends(get_ticket_service),
    conversations: ConversationService = Depends(get_conversation_service),
) -> Ticket:
    ticket = await service.get(ticket_id)
    if ticket is None:
        raise NotFoundError("Ticket not found.", details={"ticket_id": ticket_id})
    await conversations.assert_access(ticket.conversation_id, user_id=user_id)
    return ticket


@router.post(
    "/{ticket_id}/refresh",
    response_model=Ticket,
    summary="Refresh ticket status",
    description="Re-read the ticket's provider status and update the local record (owner only).",
)
async def refresh_ticket(
    ticket_id: str,
    user_id: str | None = Depends(get_user_id),
    service: TicketService = Depends(get_ticket_service),
    conversations: ConversationService = Depends(get_conversation_service),
) -> Ticket:
    ticket = await service.get(ticket_id)
    if ticket is None:
        raise NotFoundError("Ticket not found.", details={"ticket_id": ticket_id})
    await conversations.assert_access(ticket.conversation_id, user_id=user_id)
    refreshed = await service.refresh_status(ticket_id)
    if refreshed is None:
        raise NotFoundError("Ticket not found.", details={"ticket_id": ticket_id})
    return refreshed
