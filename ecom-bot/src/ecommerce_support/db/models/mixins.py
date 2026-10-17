"""Reusable column helpers for ORM models: timestamps and database enum types."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now (Python-side default for testability)."""
    return datetime.now(UTC)


def _enum_values(enum_cls: type[PyEnum]) -> list[str]:
    return [member.value for member in enum_cls]


def enum_column_type(enum_cls: type[PyEnum], name: str) -> SAEnum:
    """A non-native (VARCHAR + CHECK) enum type storing member *values*.

    Non-native enums avoid PostgreSQL ``ALTER TYPE`` pain and keep migrations portable;
    the CHECK constraint enforces the allowed values at the database level.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        values_callable=_enum_values,
        validate_strings=True,
        create_constraint=True,
        length=32,
    )


class CreatedAtMixin:
    """Adds an immutable ``created_at`` timestamp."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        nullable=False,
    )


class TimestampMixin(CreatedAtMixin):
    """Adds ``created_at`` and a ``updated_at`` that changes on update."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        server_default=func.now(),
        onupdate=utcnow,
        nullable=False,
    )
