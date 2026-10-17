"""Liveness and readiness.

The distinction matters operationally: ``/health/live`` answers "is this process
running" and must never touch the database, or a database blip would restart
every API container. ``/health/ready`` answers "can this process serve traffic"
and therefore does check its dependencies.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import text
from src.core.enums import TradingMode

from apps.api.dependencies import (
    EventsDep,
    OrdersDep,
    PortfolioDep,
    RiskDep,
    SessionDep,
    SettingsDep,
    StrategiesDep,
)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, object]:
    """Process liveness. Deliberately dependency-free."""
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@router.get("/ready")
def ready(session: SessionDep) -> dict[str, object]:
    """Readiness, including the database round trip."""
    checks: dict[str, object] = {}
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, do not raise
        checks["database"] = f"error: {type(exc).__name__}"

    try:
        from src.database.migrations import status as migration_status

        rows = migration_status(session.get_bind())
        checks["migrations"] = ",".join(f"{v}{'' if ok else ' (pending)'}" for v, _, ok in rows)
    except Exception as exc:  # noqa: BLE001
        checks["migrations"] = f"error: {type(exc).__name__}"

    ok = checks.get("database") == "ok"
    return {"status": "ok" if ok else "degraded", "checks": checks}


@router.get("/status")
def status(
    settings: SettingsDep,
    portfolio: PortfolioDep,
    orders: OrdersDep,
    risk: RiskDep,
    strategies: StrategiesDep,
    events: EventsDep,
) -> dict[str, object]:
    """A compact view of what the system currently believes.

    Everything here is read from the database rather than from memory, so this
    is what an operator sees after a restart.
    """
    mode = TradingMode(settings.trading_mode).value
    snapshot = portfolio.build_snapshot(mode)
    qualified = strategies.qualified_strategies()
    return {
        "mode": mode,
        "live_trading_enabled": settings.live_trading_enabled,
        "kill_switch": _kill_switch_state(),
        "equity_usd": snapshot.equity_usd,
        "cash_usd": snapshot.cash_usd,
        "exposure_usd": snapshot.total_exposure_usd,
        "unrealized_pnl_usd": snapshot.unrealized_pnl_usd,
        "open_positions": len(snapshot.positions),
        "orders_today": orders.count(mode=mode),
        "qualified_strategies": qualified,
        "risk_rejection_rate_24h": round(
            risk.rejection_rate(since=datetime.now(UTC).replace(hour=0, minute=0, second=0)),
            4,
        ),
        "recent_events": [
            {"level": e.level, "component": e.component, "event": e.event} for e in events.recent(limit=10)
        ],
    }


def _kill_switch_state() -> dict[str, object]:
    from src.core.security import kill_switch

    state = kill_switch.status()
    return {
        "engaged": bool(state.get("engaged")),
        "reason": state.get("reason"),
        "engaged_at": str(state.get("engaged_at")) if state.get("engaged_at") else None,
    }


__all__ = ["router", "TradingMode"]
