"""RAG evaluation result contracts (FR-055)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ecommerce_support.schemas.common import Schema


class EvalResultCreate(Schema):
    """A single metric observation for an evaluation case."""

    dataset_version: str = Field(min_length=1, max_length=64)
    case_id: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0.0, le=1.0)
    detail: dict[str, Any] = Field(default_factory=dict)


class EvalResult(Schema):
    """A persisted evaluation result."""

    id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1, max_length=64)
    case_id: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0.0, le=1.0)
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
