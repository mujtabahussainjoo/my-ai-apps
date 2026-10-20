"""Conversation endpoints (FR-002, FR-008, FR-012) with ownership enforcement (SEC-002).

``GET`` returns a conversation with its ordered messages; a paginated history sub-resource returns
messages; listing is scoped to the authenticated caller; ``DELETE`` erases the conversation and its
dependent rows. Callers can only reach conversations they own (guests own ``user_id IS NULL``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from ecommerce_support.api.dependencies import (
    get_conversation_service,
    get_required_user_id,
    get_user_id,
)
from ecommerce_support.schemas import (
    Conversation,
    ConversationSummary,
    Message,
    Page,
    PageParams,
)
from ecommerce_support.services.conversations import ConversationService

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


@router.get(
    "",
    response_model=Page[ConversationSummary],
    summary="List conversations",
    description="List the authenticated caller's conversations, newest first (FR-008).",
)
async def list_conversations(
    user_id: str = Depends(get_required_user_id),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ConversationService = Depends(get_conversation_service),
) -> Page[ConversationSummary]:
    return await service.list_for_user(user_id, params=PageParams(limit=limit, offset=offset))


@router.get(
    "/{conversation_id}",
    response_model=Conversation,
    summary="Get a conversation",
    description="Return a conversation you own with its ordered messages (FR-002, SEC-002).",
)
async def get_conversation(
    conversation_id: str,
    user_id: str | None = Depends(get_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> Conversation:
    return await service.get(conversation_id, user_id=user_id)


@router.get(
    "/{conversation_id}/messages",
    response_model=Page[Message],
    summary="Get conversation history",
    description="Return a paginated, oldest-first page of messages you own (FR-002).",
)
async def list_messages(
    conversation_id: str,
    user_id: str | None = Depends(get_user_id),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ConversationService = Depends(get_conversation_service),
) -> Page[Message]:
    return await service.list_messages(
        conversation_id, user_id=user_id, params=PageParams(limit=limit, offset=offset)
    )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation",
    description="Erase a conversation you own and its messages/tickets/feedback (FR-012).",
)
async def delete_conversation(
    conversation_id: str,
    user_id: str | None = Depends(get_user_id),
    service: ConversationService = Depends(get_conversation_service),
) -> None:
    await service.delete(conversation_id, user_id=user_id)
