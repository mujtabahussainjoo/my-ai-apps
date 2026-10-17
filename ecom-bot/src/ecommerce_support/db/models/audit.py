"""Audit event persistence (DATA-001 ``audit_events``; SEC-010)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import CreatedAtMixin


class AuditEvent(Base, CreatedAtMixin):
    """An audit record. ``detail`` must never contain secrets or full PII (SEC-010)."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_type_created", "event_type", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
