"""Feedback repository (create + reporting queries; FR-052)."""

from __future__ import annotations

from sqlalchemy import func, select

from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import Feedback as FeedbackRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import Feedback, FeedbackRequest
from ecommerce_support.schemas.enums import ResolutionOutcome


def _to_feedback(row: FeedbackRow) -> Feedback:
    return Feedback(
        id=row.id,
        conversation_id=row.conversation_id,
        rating=row.rating,
        comment=row.comment,
        resolution_outcome=row.resolution_outcome,
        created_at=row.created_at,
    )


class FeedbackRepository(BaseRepository):
    """Persist and report customer feedback."""

    async def create(self, request: FeedbackRequest, *, feedback_id: str | None = None) -> Feedback:
        row = FeedbackRow(
            id=feedback_id or new_id("fb"),
            conversation_id=request.conversation_id,
            rating=request.rating,
            comment=request.comment,
            resolution_outcome=request.resolution_outcome,
        )
        self.session.add(row)
        await self.session.flush()
        return _to_feedback(row)

    async def get(self, feedback_id: str) -> Feedback | None:
        row = await self.session.get(FeedbackRow, feedback_id)
        return _to_feedback(row) if row is not None else None

    async def list_by_conversation(self, conversation_id: str) -> list[Feedback]:
        stmt = (
            select(FeedbackRow)
            .where(FeedbackRow.conversation_id == conversation_id)
            .order_by(FeedbackRow.created_at.asc())
        )
        return [_to_feedback(row) for row in (await self.session.scalars(stmt)).all()]

    async def count_by_rating(self) -> dict[int, int]:
        stmt = (
            select(FeedbackRow.rating, func.count())
            .group_by(FeedbackRow.rating)
            .order_by(FeedbackRow.rating)
        )
        rows = (await self.session.execute(stmt)).all()
        return {int(rating): int(count) for rating, count in rows}

    async def count_by_outcome(self) -> dict[ResolutionOutcome, int]:
        stmt = (
            select(FeedbackRow.resolution_outcome, func.count())
            .where(FeedbackRow.resolution_outcome.is_not(None))
            .group_by(FeedbackRow.resolution_outcome)
        )
        rows = (await self.session.execute(stmt)).all()
        return {outcome: int(count) for outcome, count in rows if outcome is not None}
