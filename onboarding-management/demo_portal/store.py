"""In-memory state and fault injection for the demo portal.

This simulates the storage and failure behavior of the third-party
systems. It is intentionally simple and single-process: good enough to
demonstrate reconciliation, but not a production durable store.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# Fault modes the portal can inject.
SUCCESS = "success"
TIMEOUT = "timeout"           # apply the write, then fail -> unknown outcome
TEMPORARY = "temporary"       # do not apply, 503 -> safe to retry
RATE_LIMIT = "rate_limit"     # do not apply, 429 -> safe to retry later
PERMANENT = "permanent"       # do not apply, 400 -> escalate

VALID_MODES = {SUCCESS, TIMEOUT, TEMPORARY, RATE_LIMIT, PERMANENT}


@dataclass
class FaultRule:
    target: str
    operation: str
    mode: str
    remaining: int = -1  # -1 = apply forever


@dataclass
class PortalStore:
    records: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    faults: list[FaultRule] = field(default_factory=list)
    applied_keys: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    # -- fault injection ---------------------------------------------------
    def next_fault(self, target: str, operation: str) -> str:
        with self._lock:
            for rule in self.faults:
                if rule.remaining == 0:
                    continue
                if rule.target not in ("*", target):
                    continue
                if rule.operation not in ("*", operation):
                    continue
                if rule.remaining > 0:
                    rule.remaining -= 1
                return rule.mode
        return SUCCESS

    # -- idempotency -------------------------------------------------------
    def note_operation_key(self, key: str | None) -> bool:
        """Return True the first time a key is seen, False afterwards."""
        if not key:
            return True
        with self._lock:
            if key in self.applied_keys:
                return False
            self.applied_keys.add(key)
            return True

    # -- records -----------------------------------------------------------
    def upsert(self, target: str, employee_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self.records.setdefault(target, {})[employee_id] = payload

    def get(self, target: str, employee_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self.records.get(target, {}).get(employee_id)

    def all(self, target: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self.records.get(target, {}))

    # -- lifecycle ---------------------------------------------------------
    def reset(self) -> None:
        with self._lock:
            self.records.clear()
            self.events.clear()
            self.faults.clear()
            self.applied_keys.clear()


STORE = PortalStore()
