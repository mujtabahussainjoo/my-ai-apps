"""Authoritative record store (source of truth for validation).

The prototype seeds this from ``sample_events/authoritative_records.json``
which represents the official HR/Workday record. In production this would
be a real read (and, for owner systems, write) integration.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import BASE_DIR
from app.models import StandardEmployee

DEFAULT_PATH = BASE_DIR / "sample_events" / "authoritative_records.json"


class AuthoritativeStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self._records: dict[str, StandardEmployee] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            self._records = {
                str(k): StandardEmployee.from_dict(v) for k, v in raw.items()
            }

    def get(self, employee_id: str) -> StandardEmployee | None:
        return self._records.get(employee_id)

    def ids(self) -> set[str]:
        return set(self._records)

    def upsert(self, employee: StandardEmployee) -> None:
        self._records[employee.employee_id] = employee

    def all(self) -> dict[str, StandardEmployee]:
        return dict(self._records)
