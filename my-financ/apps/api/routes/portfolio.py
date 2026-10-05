"""Portfolio, orders, trades, and the risk trail.

These are the read routes an operator reaches for after something looks wrong,
so each one is answerable straight from the ledger: what is held, what was
ordered, what the engine decided, and why it refused.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from src.core.enums import TradingMode

from apps.api.dependencies import (
    OrdersDep,
    PortfolioDep,
    RiskDep,
    SettingsDep,
    TradesDep,
)

router = APIRouter(tags=["portfolio"])


def _mode(settings, requested: str | None) -> str:
    if requested is None:
        return TradingMode(settings.trading_mode).value
    try:
        return TradingMode(requested).value
    except ValueError as exc:
        allowed = ", ".join(m.value for m in TradingMode)
        raise HTTPException(
            status_code=422, detail=f"unknown mode {requested!r}; expected one of {allowed}"
        ) from exc


# ── Portfolio ───────────────────────────────────────────────────────────────


@router.get("/portfolio")
def get_portfolio(
    portfolio: PortfolioDep, settings: SettingsDep, mode: str | None = None
) -> dict[str, Any]:
    """Current balances, exposure, and P&L."""
    m = _mode(settings, mode)
    return portfolio.build_snapshot(m).model_dump(mode="json")


@router.get("/portfolio/positions")
def get_positions(
    portfolio: PortfolioDep, settings: SettingsDep, mode: str | None = None
) -> dict[str, Any]:
    m = _mode(settings, mode)
    rows = portfolio.get_positions(m)
    return {"mode": m, "count": len(rows), "positions": [p.model_dump(mode="json") for p in rows]}


@router.get("/portfolio/balances")
def get_balances(
    portfolio: PortfolioDep, settings: SettingsDep, mode: str | None = None
) -> dict[str, Any]:
    m = _mode(settings, mode)
    return {
        "mode": m,
        "usd_free": portfolio.cash_usd(m),
        "exposure_usd": portfolio.total_exposure_usd(m),
        "unrealized_pnl_usd": portfolio.unrealized_pnl_usd(m),
        "realized_pnl_usd": trades_realized(portfolio, m),
    }


def trades_realized(portfolio: PortfolioDep, mode: str) -> float:
    snapshot = portfolio.latest_snapshot(mode)
    return snapshot.realized_pnl_usd if snapshot else 0.0


@router.get("/portfolio/equity-curve")
def get_equity_curve(
    portfolio: PortfolioDep,
    settings: SettingsDep,
    mode: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
) -> dict[str, Any]:
    m = _mode(settings, mode)
    points = portfolio.equity_curve(m, limit=limit)
    return {
        "mode": m,
        "count": len(points),
        "points": [{"timestamp": t.isoformat(), "equity_usd": v} for t, v in points],
    }


# ── Orders and trades ───────────────────────────────────────────────────────


@router.get("/orders")
def list_orders(
    orders: OrdersDep,
    settings: SettingsDep,
    mode: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    m = _mode(settings, mode)
    rows = orders.recent(limit=limit, mode=m)
    if status_filter:
        rows = [r for r in rows if r.status == status_filter]
    return {
        "mode": m,
        "count": len(rows),
        "orders": [orders.to_schema(r).model_dump(mode="json") for r in rows],
    }


@router.get("/orders/{order_id}")
def get_order(order_id: str, orders: OrdersDep, risk: RiskDep) -> dict[str, Any]:
    row = orders.get(order_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no order {order_id!r}")
    assessments = risk.assessments_for_order(order_id)
    return {
        "order": orders.to_schema(row).model_dump(mode="json"),
        "risk_assessments": [
            {
                "id": a.id,
                "verdict": a.verdict,
                "risk_level": a.risk_level,
                "approved_quantity": a.approved_quantity,
                "assessed_at": a.assessed_at.isoformat() if a.assessed_at else None,
            }
            for a in assessments
        ],
    }


@router.get("/open-orders")
def open_orders(orders: OrdersDep, settings: SettingsDep, mode: str | None = None) -> dict[str, Any]:
    m = _mode(settings, mode)
    rows = orders.open_orders(mode=m)
    return {"mode": m, "count": len(rows), "orders": [orders.to_schema(r).model_dump(mode="json") for r in rows]}


@router.get("/trades")
def list_trades(
    trades: TradesDep,
    settings: SettingsDep,
    mode: str | None = None,
    open_only: bool = False,
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    m = _mode(settings, mode)
    if open_only:
        rows = trades.open_trades(mode=m)
    else:
        rows = trades.closed_trades(mode=m, limit=limit)
    return {
        "mode": m,
        "open_only": open_only,
        "count": len(rows),
        "trades": [trades.to_schema(r).model_dump(mode="json") for r in rows],
    }


@router.get("/trades/performance")
def get_performance(
    trades: TradesDep, settings: SettingsDep, mode: str | None = None
) -> dict[str, Any]:
    m = _mode(settings, mode)
    open_rows = trades.open_trades(mode=m)
    closed = trades.closed_trades(mode=m, limit=1000)
    wins = [t for t in closed if float(t.pnl_usd or 0) > 0]
    losses = [t for t in closed if float(t.pnl_usd or 0) < 0]
    gross_win = sum(float(t.pnl_usd or 0) for t in wins)
    gross_loss = abs(sum(float(t.pnl_usd or 0) for t in losses))
    return {
        "mode": m,
        "open_trades": len(open_rows),
        "closed_trades": len(closed),
        "win_rate": round(len(wins) / len(closed), 4) if closed else None,
        "realized_pnl_usd": trades.realized_pnl(mode=m),
        "gross_profit_usd": round(gross_win, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else None,
        "average_win_usd": round(gross_win / len(wins), 2) if wins else None,
        "average_loss_usd": round(-gross_loss / len(losses), 2) if losses else None,
    }


# ── Risk trail ──────────────────────────────────────────────────────────────


@router.get("/risk/failed-checks")
def failed_checks(risk: RiskDep, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    """Which rules have been refusing trades, and why."""
    rows = risk.failed_checks(limit=limit)
    return {
        "count": len(rows),
        "failed_checks": [
            {
                "rule": r.rule,
                "severity": r.severity,
                "symbol": r.symbol,
                "message": r.message,
                "observed": r.observed,
                "limit": r.limit_value,
                "unit": r.unit,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/risk/breakers")
def breaker_history(risk: RiskDep, limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    rows = risk.breaker_history(limit=limit)
    return {
        "count": len(rows),
        "breakers": [
            {
                "breaker": r.breaker,
                "action": r.action,
                "reason": r.reason,
                "value": r.value,
                "threshold": r.threshold,
                "triggered_by": r.triggered_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/risk/assessments/{symbol}")
def assessments_for_symbol(
    symbol: str, risk: RiskDep, limit: int = Query(20, ge=1, le=200)
) -> dict[str, Any]:
    rows = risk.assessments_for_symbol(symbol, limit=limit)
    return {
        "symbol": symbol,
        "count": len(rows),
        "assessments": [
            {
                "id": a.id,
                "order_id": a.order_id,
                "verdict": a.verdict,
                "risk_level": a.risk_level,
                "approved_quantity": a.approved_quantity,
                "approved_notional_usd": a.approved_notional_usd,
                "approved_risk_usd": a.approved_risk_usd,
                "assessed_at": a.assessed_at.isoformat() if a.assessed_at else None,
            }
            for a in rows
        ],
    }


__all__ = ["router"]
