"""Synchronise the operator kill switch across API and worker processes."""

from sqlalchemy import select

from src.core.security import kill_switch
from src.database.models.audit import CircuitBreakerEvent


def sync_kill_switch(session):
    row = session.scalar(
        select(CircuitBreakerEvent)
        .where(CircuitBreakerEvent.breaker == "operator_kill_switch")
        .order_by(CircuitBreakerEvent.id.desc())
        .limit(1)
    )
    if row is not None:
        if row.action == "engaged":
            kill_switch.engage(row.reason)
        else:
            kill_switch.release(operator=row.triggered_by or "persisted operator")
    return kill_switch.status()
