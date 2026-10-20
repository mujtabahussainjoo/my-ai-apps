"""Audit hooks for tool invocations (SEC-010).

Hooks receive redacted :class:`AuditEventCreate` events — never raw tool arguments, which may
carry PII or secrets. The default hook logs through structlog; tests use the in-memory recorder.
"""

from __future__ import annotations

from typing import Protocol

from ecommerce_support.core.logging import get_logger
from ecommerce_support.schemas.audit import AuditEventCreate

__all__ = ["AuditHook", "LoggingAuditHook", "RecordingAuditHook"]

_logger = get_logger("ecommerce_support.tools.audit")


class AuditHook(Protocol):
    """Sink for redacted tool audit events."""

    async def record(self, event: AuditEventCreate) -> None: ...


class LoggingAuditHook:
    """Default hook: emit each event as a structured log line (no arguments, no secrets)."""

    async def record(self, event: AuditEventCreate) -> None:
        _logger.info(
            "tool.audit",
            event_type=event.event_type,
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            conversation_id=event.conversation_id,
            **event.detail,
        )


class RecordingAuditHook:
    """In-memory hook for tests and local inspection."""

    def __init__(self) -> None:
        self.events: list[AuditEventCreate] = []

    async def record(self, event: AuditEventCreate) -> None:
        self.events.append(event)

    def event_types(self) -> list[str]:
        return [event.event_type for event in self.events]
