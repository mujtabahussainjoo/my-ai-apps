"""Feedback contracts (FR-026, FR-052)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.enums import ResolutionOutcome


class FeedbackRequest(Schema):
    """Customer rating (1-5) and optional comment for a conversation."""

    conversation_id: str = Field(min_length=1, max_length=64)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    resolution_outcome: ResolutionOutcome | None = None

    @field_validator("comment")
    @classmethod
    def _normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class Feedback(Schema):
    """A persisted feedback record (FR-052)."""

    id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    resolution_outcome: ResolutionOutcome | None = None
    created_at: datetime
