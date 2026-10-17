"""Common schema building blocks: base models, pagination, error envelope.

Two base styles:

- :class:`Schema` — request/response/domain contracts. Unknown fields are rejected so
  clients cannot smuggle unexpected attributes (mass-assignment defense).
- :class:`ORMReadableSchema` — for models populated from persistence rows (``from_attributes``).

These are plain Pydantic v2 models with no framework or persistence dependencies.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CURRENCY_PATTERN = r"^[A-Z]{3}$"


class Schema(BaseModel):
    """Base for API/agent/tool contracts; rejects unknown fields and strips whitespace."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ORMReadableSchema(BaseModel):
    """Base for models built from ORM rows; ignores extras and reads attributes."""

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
        from_attributes=True,
    )


class ErrorDetail(Schema):
    """Machine-readable error payload (mirrors ``core.exceptions.AppError``)."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class ErrorResponse(Schema):
    """Standard error envelope returned on all API failures."""

    error: ErrorDetail
    request_id: str | None = None


class PageParams(Schema):
    """Pagination query parameters with bounded limits (FR-008)."""

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class Page[T](BaseModel):
    """A paginated slice of a homogeneous collection."""

    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)

    @property
    def has_more(self) -> bool:
        """True when more items remain after this slice."""
        return self.offset + len(self.items) < self.total
