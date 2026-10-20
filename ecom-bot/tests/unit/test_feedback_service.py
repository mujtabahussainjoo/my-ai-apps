"""Unit tests for FeedbackService (TASK-030) using in-memory repository fakes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.schemas import (
    AuditEventCreate,
    Conversation,
    Feedback,
    FeedbackReport,
    FeedbackRequest,
)
from ecommerce_support.schemas.enums import ResolutionOutcome
from ecommerce_support.services import FeedbackService


def _conversation(conversation_id: str = "conv-1", user_id: str | None = "cust-1") -> Conversation:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    return Conversation(id=conversation_id, user_id=user_id, created_at=now, updated_at=now)


class FakeConversations:
    def __init__(self, conversation: Conversation | None) -> None:
        self._conversation = conversation

    async def get(self, conversation_id: str) -> Conversation | None:
        if self._conversation and self._conversation.id == conversation_id:
            return self._conversation
        return None


class FakeFeedback:
    def __init__(self) -> None:
        self.created: list[Feedback] = []
        self.report_result = FeedbackReport(total=2, average_rating=4.0, by_rating={4: 2})

    async def create(self, request: FeedbackRequest, *, feedback_id: str | None = None) -> Feedback:
        row = Feedback(
            id=feedback_id or "fb_1",
            conversation_id=request.conversation_id,
            rating=request.rating,
            comment=request.comment,
            resolution_outcome=request.resolution_outcome,
            created_at=datetime(2026, 10, 2, tzinfo=UTC),
        )
        self.created.append(row)
        return row

    async def list_by_conversation(self, conversation_id: str) -> list[Feedback]:
        return [f for f in self.created if f.conversation_id == conversation_id]

    async def report(self) -> FeedbackReport:
        return self.report_result


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEventCreate] = []

    async def record(self, event: AuditEventCreate) -> AuditEventCreate:
        self.events.append(event)
        return event


def _service(
    conversation: Conversation | None,
    *,
    feedback: FakeFeedback | None = None,
    audit: FakeAudit | None = None,
) -> tuple[FeedbackService, FakeFeedback, FakeAudit]:
    fb = feedback or FakeFeedback()
    au = audit or FakeAudit()
    service = FeedbackService(
        feedback=fb,  # type: ignore[arg-type]
        conversations=FakeConversations(conversation),  # type: ignore[arg-type]
        audit=au,  # type: ignore[arg-type]
    )
    return service, fb, au


async def test_create_persists_and_audits() -> None:
    service, feedback, audit = _service(_conversation())
    result = await service.create(
        FeedbackRequest(
            conversation_id="conv-1",
            rating=5,
            comment="great",
            resolution_outcome=ResolutionOutcome.RESOLVED,
        )
    )
    assert result.rating == 5
    assert len(feedback.created) == 1
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.event_type == "feedback.submitted"
    assert event.actor_id == "cust-1"
    assert event.conversation_id == "conv-1"
    assert event.detail == {"rating": 5, "has_comment": True, "resolution_outcome": "resolved"}


async def test_audit_detail_never_includes_comment_text() -> None:
    service, _, audit = _service(_conversation())
    await service.create(
        FeedbackRequest(conversation_id="conv-1", rating=1, comment="my card 4111 is broken")
    )
    assert "4111" not in str(audit.events[0].detail)
    assert audit.events[0].detail["has_comment"] is True


async def test_actor_falls_back_to_conversation_user() -> None:
    service, _, audit = _service(_conversation(user_id="cust-9"))
    await service.create(FeedbackRequest(conversation_id="conv-1", rating=4))
    assert audit.events[0].actor_id == "cust-9"


async def test_explicit_actor_overrides() -> None:
    service, _, audit = _service(_conversation())
    await service.create(FeedbackRequest(conversation_id="conv-1", rating=4), actor_id="agent-7")
    assert audit.events[0].actor_id == "agent-7"


async def test_missing_conversation_raises_not_found() -> None:
    service, feedback, audit = _service(None)
    with pytest.raises(NotFoundError) as excinfo:
        await service.create(FeedbackRequest(conversation_id="conv-x", rating=5))
    assert excinfo.value.code == "not_found"
    assert feedback.created == []
    assert audit.events == []


async def test_list_and_report_delegate() -> None:
    service, _, _ = _service(_conversation())
    await service.create(FeedbackRequest(conversation_id="conv-1", rating=3))
    assert len(await service.list_for_conversation("conv-1")) == 1
    assert (await service.report()).total == 2
