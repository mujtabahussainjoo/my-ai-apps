"""Ticketing/escalation contracts (FR-025, FR-043, FR-044, FR-050, FR-053).

Ticket payloads are built from these typed models; redaction and secret-stripping are
enforced by ``guardrails/`` before dispatch (FR-051).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ecommerce_support.schemas.agents import SourceCitation
from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.enums import Priority, TicketProvider, TicketStatus


class TicketRequest(Schema):
    """Structured escalation payload (FR-050). Redacted before external dispatch."""

    conversation_id: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    priority: Priority = Priority.MEDIUM
    order_id: str | None = None
    product_ids: list[str] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)
    steps_attempted: list[str] = Field(default_factory=list)
    expected_behavior: str | None = Field(default=None, max_length=2000)
    actual_behavior: str | None = Field(default=None, max_length=2000)
    requires_confirmation: bool = False
    idempotency_key: str | None = Field(default=None, max_length=128)


class Ticket(Schema):
    """A support ticket persisted from a confirmed external creation (FR-043/044)."""

    id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    provider: TicketProvider
    status: TicketStatus
    summary: str = Field(min_length=1, max_length=255)
    priority: Priority = Priority.MEDIUM
    external_id: str | None = None
    url: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime | None = None


class TicketStatusResponse(Schema):
    """Customer-queryable ticket status (FR-053)."""

    ticket_id: str = Field(min_length=1)
    provider: TicketProvider
    status: TicketStatus
    url: str | None = None
    updated_at: datetime | None = None
