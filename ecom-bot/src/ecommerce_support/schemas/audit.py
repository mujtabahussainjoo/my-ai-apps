"""Audit event contracts (SEC-010). Details carry no secrets or full PII."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ecommerce_support.schemas.common import Schema


class AuditEventCreate(Schema):
    """Input for recording an audit event (redacted detail only)."""

    event_type: str = Field(min_length=1, max_length=100)
    actor_id: str | None = Field(default=None, max_length=64)
    resource_type: str | None = Field(default=None, max_length=100)
    resource_id: str | None = Field(default=None, max_length=64)
    conversation_id: str | None = Field(default=None, max_length=64)
    detail: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(Schema):
    """A persisted audit event."""

    id: str = Field(min_length=1)
    event_type: str = Field(min_length=1, max_length=100)
    actor_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    conversation_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
