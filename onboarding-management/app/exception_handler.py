"""Exception handling: persist unresolved problems for human review.

Exceptions stay OPEN until an authorised person resolves them. Each
exception stores the field, the conflicting source values and the
reason, exactly as the brief requires. Duplicate open exceptions for the
same field are updated rather than re-created.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models import ExceptionRecord

OPEN = "OPEN"
RESOLVED = "RESOLVED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExceptionHandler:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(settings.exceptions_path)
        self._lock = threading.Lock()
        self._records: dict[str, ExceptionRecord] = {}
        self._load()

    def open_exception(
        self,
        *,
        employee_id: str,
        event_id: str,
        exception_type: str,
        reason: str,
        field_name: str | None = None,
        source_values: dict[str, Any] | None = None,
        recommended_action: str | None = None,
        ai_used: bool = False,
    ) -> ExceptionRecord:
        with self._lock:
            for record in self._records.values():
                if (
                    record.status == OPEN
                    and record.employee_id == employee_id
                    and record.event_id == event_id
                    and record.exception_type == exception_type
                    and record.field_name == field_name
                ):
                    record.reason = reason
                    if source_values:
                        record.source_values = source_values
                    if recommended_action is not None:
                        record.recommended_action = recommended_action
                    record.ai_used = record.ai_used or ai_used
                    self._save_locked()
                    return record

            record = ExceptionRecord(
                employee_id=employee_id,
                event_id=event_id,
                exception_type=exception_type,
                reason=reason,
                exception_id=f"exc-{uuid.uuid4().hex[:12]}",
                field_name=field_name,
                source_values=source_values or {},
                recommended_action=recommended_action,
                ai_used=ai_used,
                status=OPEN,
                created_at=_now(),
            )
            self._records[record.exception_id] = record
            self._save_locked()
            return record

    def resolve(
        self, exception_id: str, *, by: str, resolution: str
    ) -> ExceptionRecord | None:
        with self._lock:
            record = self._records.get(exception_id)
            if record is None:
                return None
            record.status = RESOLVED
            record.resolved_by = by
            record.resolution = resolution
            self._save_locked()
            return record

    def get(self, exception_id: str) -> ExceptionRecord | None:
        with self._lock:
            return self._records.get(exception_id)

    def all(self) -> list[ExceptionRecord]:
        with self._lock:
            return list(self._records.values())

    def open_exceptions(self) -> list[ExceptionRecord]:
        return [r for r in self.all() if r.status == OPEN]

    def for_employee(self, employee_id: str) -> list[ExceptionRecord]:
        return [r for r in self.all() if r.employee_id == employee_id]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._save_locked()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except (ValueError, OSError):
            return
        self._records = {
            key: ExceptionRecord.from_dict(value) for key, value in raw.items()
        }

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: rec.to_dict() for key, rec in self._records.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        os.replace(tmp, self.path)
