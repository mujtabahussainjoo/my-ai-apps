"""Integration tests for FeedbackService against the live schema (TASK-030).

Skipped when PostgreSQL is unreachable; runs inside a rolled-back transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.db.repositories import (
    AuditEventRepository,
    ConversationRepository,
)
from ecommerce_support.schemas import FeedbackRequest
from ecommerce_support.schemas.enums import ResolutionOutcome
from ecommerce_support.services import FeedbackService

pytestmark = pytest.mark.integration


async def test_feedback_service_create_is_saved_and_audited(session: AsyncSession) -> None:
    conversation = await ConversationRepository(session).create(user_id=None)
    service = FeedbackService.from_session(session)

    created = await service.create(
        FeedbackRequest(
            conversation_id=conversation.id,
            rating=5,
            comment="very helpful",
            resolution_outcome=ResolutionOutcome.RESOLVED,
        )
    )
    stored = await service.list_for_conversation(conversation.id)
    assert [f.id for f in stored] == [created.id]

    events = await AuditEventRepository(session).list_for_conversation(conversation.id)
    assert [e.event_type for e in events] == ["feedback.submitted"]
    assert events[0].detail["rating"] == 5
    assert "very helpful" not in str(events[0].detail)

    report = await service.report()
    assert report.total >= 1
    assert report.by_rating.get(5, 0) >= 1
    assert report.by_outcome.get(ResolutionOutcome.RESOLVED, 0) >= 1


async def test_feedback_service_rejects_unknown_conversation(session: AsyncSession) -> None:
    service = FeedbackService.from_session(session)
    with pytest.raises(NotFoundError):
        await service.create(FeedbackRequest(conversation_id="conv-does-not-exist", rating=4))
