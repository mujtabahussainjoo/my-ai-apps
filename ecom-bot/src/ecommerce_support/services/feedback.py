"""Feedback use-case: persist ratings linked to a conversation + outcome, and report (FR-026/052).

Plain Python (no web/graph imports). Business rules live here — the conversation must exist before a
rating is accepted, and every submission is audited with a redacted detail (no comment text, SEC-010).
Repositories only ``flush``; transaction commit is the caller's/transport's responsibility.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.core.metrics import (
    COUNTER_FEEDBACK,
    HISTOGRAM_FEEDBACK_RATING,
    get_metrics,
)
from ecommerce_support.db.repositories import (
    AuditEventRepository,
    ConversationRepository,
    FeedbackRepository,
)
from ecommerce_support.schemas import (
    AuditEventCreate,
    Feedback,
    FeedbackReport,
    FeedbackRequest,
)

FEEDBACK_SUBMITTED_EVENT = "feedback.submitted"


class FeedbackService:
    """Records customer feedback and serves reporting queries."""

    def __init__(
        self,
        *,
        feedback: FeedbackRepository,
        conversations: ConversationRepository,
        audit: AuditEventRepository,
    ) -> None:
        self._feedback = feedback
        self._conversations = conversations
        self._audit = audit

    @classmethod
    def from_session(cls, session: AsyncSession) -> FeedbackService:
        """Build the service from a DB session (repositories share its transaction)."""
        return cls(
            feedback=FeedbackRepository(session),
            conversations=ConversationRepository(session),
            audit=AuditEventRepository(session),
        )

    async def create(
        self,
        request: FeedbackRequest,
        *,
        actor_id: str | None = None,
    ) -> Feedback:
        """Persist a rating for an existing conversation and audit the submission.

        Raises :class:`NotFoundError` when the conversation does not exist so a rating cannot be
        attached to nothing.
        """
        conversation = await self._conversations.get(request.conversation_id)
        if conversation is None:
            raise NotFoundError(
                "Conversation not found.",
                details={"conversation_id": request.conversation_id},
            )

        feedback = await self._feedback.create(request)
        metrics = get_metrics()
        metrics.increment(COUNTER_FEEDBACK, rating=str(feedback.rating))
        metrics.observe(HISTOGRAM_FEEDBACK_RATING, float(feedback.rating))
        await self._audit.record(
            AuditEventCreate(
                event_type=FEEDBACK_SUBMITTED_EVENT,
                actor_id=actor_id or conversation.user_id,
                resource_type="feedback",
                resource_id=feedback.id,
                conversation_id=conversation.id,
                detail={
                    "rating": feedback.rating,
                    "has_comment": feedback.comment is not None,
                    "resolution_outcome": (
                        feedback.resolution_outcome.value
                        if feedback.resolution_outcome is not None
                        else None
                    ),
                },
            )
        )
        return feedback

    async def list_for_conversation(self, conversation_id: str) -> list[Feedback]:
        """Return all feedback for a conversation (FR-052 query-by-conversation)."""
        return await self._feedback.list_by_conversation(conversation_id)

    async def report(self) -> FeedbackReport:
        """Aggregate feedback by rating and resolution outcome (FR-052/FR-055)."""
        return await self._feedback.report()
