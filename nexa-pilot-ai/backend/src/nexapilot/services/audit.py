"""Audit trail helper.

Records *what happened*, never sensitive payloads: no message bodies, no tokens,
no payment details.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from nexapilot.db.models import AuditLog


def record(
    session: Session,
    *,
    action: str,
    target: str = "",
    status: str = "ok",
    actor: str = "user",
    details: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        target=target[:300],
        status=status,
        details=details or {},
    )
    session.add(entry)
    return entry
