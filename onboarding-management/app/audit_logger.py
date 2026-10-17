"""Audit trail.

Writes one JSON object per line to ``data/audit_log.jsonl`` so the
history can be replayed. Sensitive values are minimized/masked and
credentials are never logged.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models import ExceptionRecord, OperationOutcome, RawEvent

# Fields whose raw values are masked in the audit trail (privacy).
_SENSITIVE_FIELDS = {"personal_email"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask(field_name: str, value: Any) -> Any:
    if field_name in _SENSITIVE_FIELDS and isinstance(value, str) and "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"
    return value


class AuditLogger:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(settings.audit_path)
        self._lock = threading.Lock()

    # -- public API --------------------------------------------------------
    def log_workflow(
        self,
        *,
        result: Any,
        event: RawEvent,
        employee_before: dict[str, Any] | None,
        employee_after: dict[str, Any] | None,
    ) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        for name in result.changed_fields:
            previous = (employee_before or {}).get(name)
            new = (employee_after or {}).get(name)
            changes[name] = {
                "previous": _mask(name, previous),
                "new": _mask(name, new),
            }

        entry = {
            "entry_type": "workflow",
            "employee_id": result.employee_id,
            "event_id": result.event_id,
            "source": result.source,
            "event_type": result.event_type,
            "event_timestamp": event.received_at,
            "processing_timestamp": _now(),
            "changed_fields": list(result.changed_fields),
            "changes": changes,
            "validation": result.validation,
            "overall_status": result.overall_status.value,
            "message": result.message,
            "blocked": result.blocked,
            "operations": [self._operation(o) for o in result.outcomes],
            "exception_ids": list(result.exceptions),
        }
        self._append(entry)
        return entry

    def log_exception_resolution(
        self, record: ExceptionRecord, *, action: str = "resolved"
    ) -> dict[str, Any]:
        entry = {
            "entry_type": "exception",
            "action": action,
            "exception_id": record.exception_id,
            "employee_id": record.employee_id,
            "event_id": record.event_id,
            "exception_type": record.exception_type,
            "field_name": record.field_name,
            "status": record.status,
            "recommended_action": record.recommended_action,
            "ai_used": record.ai_used,
            "resolved_by": record.resolved_by,
            "resolution": record.resolution,
            "processing_timestamp": _now(),
        }
        self._append(entry)
        return entry

    def read(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text().splitlines()
        if limit is not None:
            lines = lines[-limit:]
        entries: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def clear(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("")

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _operation(outcome: OperationOutcome) -> dict[str, Any]:
        clean = outcome.status in {"SUCCESS", "SKIPPED_IDEMPOTENT"}
        return {
            "target": outcome.target,
            "operation": outcome.operation,
            "status": outcome.status,
            "attempts": outcome.attempts,
            "detail": outcome.detail,
            "error_category": outcome.failure_kind,
            "error_message": None if clean else outcome.detail,
        }

    def _append(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
