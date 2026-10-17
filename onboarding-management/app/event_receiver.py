"""Receive and sanity-check incoming hiring/change events.

Malformed events are rejected *before* any processing so bad envelopes
never reach normalization or downstream systems.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models import RawEvent

REQUIRED_ENVELOPE_FIELDS = ("event_id", "source", "employee_id", "event_type")


class MalformedEventError(ValueError):
    """Raised when an event envelope is missing required structure."""


def parse_event(payload: Any) -> RawEvent:
    if not isinstance(payload, dict):
        raise MalformedEventError("event payload must be a JSON object")

    missing = [name for name in REQUIRED_ENVELOPE_FIELDS if not payload.get(name)]
    if missing:
        raise MalformedEventError(
            f"event is missing required field(s): {', '.join(missing)}"
        )

    employee = payload.get("employee", {})
    if employee is not None and not isinstance(employee, dict):
        raise MalformedEventError("'employee' must be a JSON object")

    changed = payload.get("changed_fields", [])
    if changed is not None and not isinstance(changed, list):
        raise MalformedEventError("'changed_fields' must be a list")

    return RawEvent.from_dict(payload)


def load_event(path: str | Path) -> RawEvent:
    data = json.loads(Path(path).read_text())
    return parse_event(data)
