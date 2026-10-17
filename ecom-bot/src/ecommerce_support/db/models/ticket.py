"""Support ticket persistence with idempotency (DATA-001; FR-043, FR-044)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import TimestampMixin, enum_column_type
from ecommerce_support.schemas.enums import Priority, TicketProvider, TicketStatus


class SupportTicket(Base, TimestampMixin):
    """An escalated ticket. ``idempotency_key`` is unique to prevent duplicates (FR-043)."""

    __tablename__ = "support_tickets"
    __table_args__ = (Index("ix_support_tickets_conversation", "conversation_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", server_default="default", index=True
    )
    provider: Mapped[TicketProvider] = mapped_column(
        enum_column_type(TicketProvider, "ticket_provider"), nullable=False
    )
    status: Mapped[TicketStatus] = mapped_column(
        enum_column_type(TicketStatus, "ticket_status"), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[Priority] = mapped_column(
        enum_column_type(Priority, "ticket_priority"), nullable=False, default=Priority.MEDIUM
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), nullable=True, unique=True, index=True
    )
    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
