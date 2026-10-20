"""End-to-end feedback capture and reporting (FR-052, mocks only)."""

from __future__ import annotations

from typing import Any

import pytest

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.schemas import ChatRequest, FeedbackRequest
from ecommerce_support.schemas.enums import ResolutionOutcome

pytestmark = pytest.mark.e2e


async def _conversation(stack: Any, user_id: str = "cust-1") -> str:
    response = await stack.chat.chat(
        ChatRequest(message="Where is my order ord-1?"), user_id=user_id
    )
    return response.conversation_id


class TestFeedback:
    async def test_submit_and_list_feedback(self, e2e_stack: Any) -> None:
        conversation_id = await _conversation(e2e_stack)
        feedback = await e2e_stack.feedback.create(
            FeedbackRequest(
                conversation_id=conversation_id,
                rating=5,
                comment="Great help!",
                resolution_outcome=ResolutionOutcome.RESOLVED,
            ),
            actor_id="cust-1",
        )
        assert feedback.rating == 5
        listed = await e2e_stack.feedback.list_for_conversation(conversation_id)
        assert [f.id for f in listed] == [feedback.id]

    async def test_report_aggregates_ratings(self, e2e_stack: Any) -> None:
        conversation_id = await _conversation(e2e_stack)
        for rating in (4, 2):
            await e2e_stack.feedback.create(
                FeedbackRequest(conversation_id=conversation_id, rating=rating),
                actor_id="cust-1",
            )
        report = await e2e_stack.feedback.report()
        assert report.total == 2
        assert report.average_rating == 3.0
        assert report.by_rating == {2: 1, 4: 1}

    async def test_feedback_for_unknown_conversation_is_rejected(self, e2e_stack: Any) -> None:
        with pytest.raises(NotFoundError):
            await e2e_stack.feedback.create(
                FeedbackRequest(conversation_id="conv-missing", rating=5),
                actor_id="cust-1",
            )

    async def test_feedback_records_audit_event(self, e2e_stack: Any) -> None:
        conversation_id = await _conversation(e2e_stack)
        await e2e_stack.feedback.create(
            FeedbackRequest(conversation_id=conversation_id, rating=3),
            actor_id="cust-1",
        )
        assert any(e.event_type.startswith("feedback") for e in e2e_stack.audit.rows)


class TestTicketRetrieval:
    async def test_list_for_conversation_is_empty_without_escalation(self, e2e_stack: Any) -> None:
        conversation_id = await _conversation(e2e_stack)
        assert await e2e_stack.tickets.list_for_conversation(conversation_id) == []

    async def test_missing_conversation_feedback_is_rejected(self, e2e_stack: Any) -> None:
        with pytest.raises(NotFoundError):
            await e2e_stack.feedback.create(FeedbackRequest(conversation_id="missing", rating=3))
