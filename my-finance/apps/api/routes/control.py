"""Authenticated operator decisions. These routes never submit venue orders."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from src.database.models.audit import SystemEvent
from src.database.models.trading import Approval
from src.risk.operator_controls import sync_kill_switch

from apps.api.dependencies import ApprovalsDep, OperatorDep, RiskDep, SessionDep

router = APIRouter(prefix="/control", tags=["operator"])


class OperatorDecision(BaseModel):
    approved: bool
    reason: str = Field(min_length=10, max_length=500)


class BreakerDecision(BaseModel):
    engaged: bool
    reason: str = Field(min_length=10, max_length=500)


@router.get("/kill-switch")
def breaker_status(session: SessionDep):
    return sync_kill_switch(session)


@router.post("/kill-switch")
def set_breaker(body: BreakerDecision, operator: OperatorDep, risk: RiskDep, session: SessionDep):
    risk.log_breaker(
        "operator_kill_switch", "engaged" if body.engaged else "released", body.reason, triggered_by=operator
    )
    session.commit()
    return sync_kill_switch(session)


@router.get("/approvals")
def approvals(session: SessionDep):
    rows = session.scalars(select(Approval).order_by(Approval.created_at.desc()).limit(100))
    proposals = {}
    for event in session.scalars(
        select(SystemEvent)
        .where(SystemEvent.component == "assisted", SystemEvent.event == "order_proposed")
        .order_by(SystemEvent.id.desc())
        .limit(1000)
    ):
        context = event.context or {}
        proposals.setdefault(context.get("approval_id"), context.get("request"))
    return {
        "approvals": [
            {
                "id": row.id,
                "fingerprint": row.fingerprint,
                "request": proposals.get(row.id),
                "status": row.status,
                "operator": row.approved_by,
                "note": row.note,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


@router.post("/approvals/{approval_id}")
def decide(
    approval_id: str,
    body: OperatorDecision,
    operator: OperatorDep,
    approvals: ApprovalsDep,
    session: SessionDep,
):
    try:
        row = approvals.decide(approval_id, body.approved, operator, body.reason)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if row is None:
        raise HTTPException(404, "Approval not found")
    session.commit()
    return {"id": row.id, "status": row.status, "operator": operator}
