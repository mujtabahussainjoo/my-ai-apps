"""Feedback endpoints (FR-026, FR-052): submit a rating and report on outcomes.

First versioned router (`/api/v1`). Persistence and business rules live in
:class:`~ecommerce_support.services.feedback.FeedbackService`; the route only validates input and
maps to HTTP.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from ecommerce_support.api.dependencies import (
    get_conversation_service,
    get_feedback_service,
    get_user_id,
    require_scope,
)
from ecommerce_support.schemas import Feedback, FeedbackReport, FeedbackRequest
from ecommerce_support.services import FeedbackService
from ecommerce_support.services.conversations import ConversationService

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

SUPPORT_SCOPE = "support:admin"


@router.post(
    "",
    response_model=Feedback,
    status_code=status.HTTP_201_CREATED,
    summary="Submit customer feedback",
    description="Record a 1-5 rating (optional comment) against a conversation you own.",
)
async def submit_feedback(
    request: FeedbackRequest,
    user_id: str | None = Depends(get_user_id),
    service: FeedbackService = Depends(get_feedback_service),
    conversations: ConversationService = Depends(get_conversation_service),
) -> Feedback:
    await conversations.assert_access(request.conversation_id, user_id=user_id)
    return await service.create(request)


@router.get(
    "/report",
    response_model=FeedbackReport,
    summary="Feedback report",
    description="Aggregate feedback by rating and resolution outcome (admin scope; FR-052).",
    dependencies=[Depends(require_scope(SUPPORT_SCOPE))],
)
async def feedback_report(
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackReport:
    return await service.report()


@router.get(
    "",
    response_model=list[Feedback],
    summary="List feedback",
    description="List feedback for a conversation you own (FR-052).",
)
async def list_feedback(
    conversation_id: str = Query(min_length=1, max_length=64),
    user_id: str | None = Depends(get_user_id),
    service: FeedbackService = Depends(get_feedback_service),
    conversations: ConversationService = Depends(get_conversation_service),
) -> list[Feedback]:
    await conversations.assert_access(conversation_id, user_id=user_id)
    return await service.list_for_conversation(conversation_id)
