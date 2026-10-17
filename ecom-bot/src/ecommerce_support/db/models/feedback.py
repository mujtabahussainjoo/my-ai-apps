"""Feedback persistence (DATA-001 ``feedback``; FR-026, FR-052)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import CreatedAtMixin, enum_column_type
from ecommerce_support.schemas.enums import ResolutionOutcome


class Feedback(Base, CreatedAtMixin):
    """A customer rating (1-5) with optional comment for a conversation."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
        Index("ix_feedback_conversation", "conversation_id"),
        Index("ix_feedback_rating", "rating"),
        Index("ix_feedback_outcome", "resolution_outcome"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_outcome: Mapped[ResolutionOutcome | None] = mapped_column(
        enum_column_type(ResolutionOutcome, "feedback_resolution_outcome"), nullable=True
    )
