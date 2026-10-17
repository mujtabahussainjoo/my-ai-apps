"""Idempotency ledger.

Events may be delivered more than once and retries may happen after a
timeout. Before performing a side effect we look up an operation key
``employee_id|event_id|target|operation`` and skip work that already
succeeded.

Persistence is a JSON file so the ledger survives a process restart in
the demo. Production would swap this for a real durable store.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import FailureKind, OperationRecord, OperationStatus

# Statuses that mean "the side effect is done; never repeat it".
_DONE_STATUSES = {OperationStatus.SUCCESS.value, OperationStatus.SKIPPED_IDEMPOTENT.value}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (OperationStatus, FailureKind)):
        return value.value
    return str(value)


class IdempotencyStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(settings.ledger_path)
        self._lock = threading.Lock()
        self._records: dict[str, OperationRecord] = {}
        self._load()

    # -- key ---------------------------------------------------------------
    @staticmethod
    def operation_key(
        employee_id: str, event_id: str, target: str, operation: str
    ) -> str:
        return "|".join([employee_id, event_id, target, operation])

    # -- reads -------------------------------------------------------------
    def get(self, key: str) -> OperationRecord | None:
        with self._lock:
            return self._records.get(key)

    def is_done(self, key: str) -> bool:
        record = self.get(key)
        return record is not None and record.status in _DONE_STATUSES

    def all(self) -> dict[str, OperationRecord]:
        with self._lock:
            return dict(self._records)

    # -- writes ------------------------------------------------------------
    def record(
        self,
        employee_id: str,
        event_id: str,
        target: str,
        operation: str,
        status: OperationStatus | str,
        *,
        error: str | None = None,
        failure_kind: FailureKind | str | None = None,
        attempt_delta: int = 1,
    ) -> OperationRecord:
        key = self.operation_key(employee_id, event_id, target, operation)
        with self._lock:
            record = self._records.get(key)
            if record is None:
                record = OperationRecord(
                    operation_key=key,
                    employee_id=employee_id,
                    event_id=event_id,
                    target=target,
                    operation=operation,
                    attempts=0,
                )
            record.attempts += max(attempt_delta, 0)
            record.status = _coerce(status) or OperationStatus.PENDING.value
            record.last_error = error
            record.failure_kind = _coerce(failure_kind)
            record.updated_at = _now()
            self._records[key] = record
            self._save_locked()
            return record

    def mark_skipped(
        self, employee_id: str, event_id: str, target: str, operation: str
    ) -> OperationRecord:
        """Record that a duplicate was skipped without repeating side effects."""
        return self.record(
            employee_id,
            event_id,
            target,
            operation,
            OperationStatus.SKIPPED_IDEMPOTENT,
            attempt_delta=0,
        )

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
            key: OperationRecord.from_dict(value) for key, value in raw.items()
        }

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: rec.to_dict() for key, rec in self._records.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        os.replace(tmp, self.path)


def default_ledger() -> IdempotencyStore:
    return IdempotencyStore()
