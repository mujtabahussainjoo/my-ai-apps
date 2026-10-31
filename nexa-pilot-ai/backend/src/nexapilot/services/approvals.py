"""Approval workflow.

Actions that touch the outside world (sending email, booking travel, placing
orders, running destructive commands) must be approved explicitly, immediately
before execution. The approval record is persisted so a resumed workflow can
verify that the approval applied to *this* action.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexapilot.core.errors import ApprovalRequiredError, NotFoundError
from nexapilot.db.models import ApprovalRequest

TERMINAL_STATES = frozenset({"approved", "rejected", "expired", "executed"})


def _audit(
    session: Session, *, action: str, target: str, status: str, details: dict[str, Any]
) -> None:
    from nexapilot.services.audit import record

    record(session, action=action, target=target, status=status, details=details, actor="user")


def create_request(
    session: Session,
    *,
    action: str,
    title: str = "",
    description: str = "",
    target: str = "",
    provider: str = "",
    risk: str = "low",
    cost: str = "",
    consequences: str = "",
    payload: dict[str, Any] | None = None,
    task_run_id: str = "",
) -> ApprovalRequest:
    request = ApprovalRequest(
        task_run_id=task_run_id,
        action=action,
        title=title or action,
        description=description,
        target=target,
        provider=provider,
        risk=risk,
        cost=cost,
        consequences=consequences,
        payload=payload or {},
        status="pending",
    )
    session.add(request)
    session.flush()
    return request


def get_request(session: Session, approval_id: str) -> ApprovalRequest:
    request = session.get(ApprovalRequest, approval_id)
    if request is None:
        raise NotFoundError(f"Approval request '{approval_id}' not found")
    return request


def list_requests(
    session: Session, *, status: str | None = None, limit: int = 100
) -> list[ApprovalRequest]:
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    return list(session.scalars(stmt))


def decide(
    session: Session,
    approval_id: str,
    *,
    approved: bool,
    note: str = "",
) -> ApprovalRequest:
    request = get_request(session, approval_id)
    if request.status in TERMINAL_STATES:
        raise ApprovalRequiredError(
            f"Approval request '{approval_id}' was already decided ({request.status})"
        )
    request.status = "approved" if approved else "rejected"
    request.decided_at = datetime.now(UTC)
    request.decision_note = note[:2000]
    _audit(
        session,
        action=f"approval.{request.status}",
        target=request.action,
        status=request.status,
        details={"approval_id": request.id, "risk": request.risk},
    )
    session.flush()
    return request


def mark_executed(session: Session, approval_id: str) -> ApprovalRequest:
    request = get_request(session, approval_id)
    request.status = "executed"
    _audit(
        session,
        action="approval.executed",
        target=request.action,
        status="executed",
        details={"approval_id": request.id},
    )
    session.flush()
    return request


def assert_approved(session: Session, approval_id: str) -> ApprovalRequest:
    """Raise unless the given approval was granted (and not yet consumed)."""
    request = get_request(session, approval_id)
    if request.status != "approved":
        raise ApprovalRequiredError(
            f"Action '{request.action}' is not approved (status: {request.status})",
            details={"approval_id": approval_id, "action": request.action},
        )
    return request


def require_approval(
    session: Session,
    *,
    action: str,
    payload: dict[str, Any] | None = None,
    title: str = "",
    description: str = "",
    target: str = "",
    provider: str = "",
    risk: str = "low",
    cost: str = "",
    consequences: str = "",
    task_run_id: str = "",
) -> ApprovalRequest:
    """Create a pending approval request and raise :class:`ApprovalRequiredError`."""
    request = create_request(
        session,
        action=action,
        title=title,
        description=description,
        target=target,
        provider=provider,
        risk=risk,
        cost=cost,
        consequences=consequences,
        payload=payload or {},
        task_run_id=task_run_id,
    )
    session.commit()
    raise ApprovalRequiredError(
        f"Approval required for '{action}'",
        details={
            "approval_id": request.id,
            "action": request.action,
            "title": request.title,
            "description": request.description,
            "target": request.target,
            "provider": request.provider,
            "risk": request.risk,
            "cost": request.cost,
            "consequences": request.consequences,
        },
    )
