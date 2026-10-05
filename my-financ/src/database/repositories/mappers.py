"""Schema conversion between Pydantic models and ORM rows.

One module owns every ``to_row`` / ``to_model`` pair so that:

* the Decimal / float boundary is crossed in exactly one place, and
* a round trip ``model -> row -> model`` is testable and lossless for the fields
  that matter.

The domain schemas use ``float`` while the columns are ``NUMERIC``. Reading a
row back therefore yields ``Decimal``, and every consumer in the codebase
expects ``float``. Reading is wrapped so callers never see a ``Decimal``
surprise in an arithmetic expression.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from src.core.enums import OrderSide, SignalAction, Timeframe, TradingMode
from src.schemas.market import Candle
from src.schemas.order import Order as OrderSchema
from src.schemas.portfolio import Balance, PortfolioSnapshot, Position
from src.schemas.risk import RiskAssessment
from src.schemas.signal import Signal
from src.schemas.trade import Trade as TradeSchema

ZERO = Decimal("0")


def f(value: Any) -> float:
    """Coerce a DB numeric to ``float`` for the domain layer."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def opt_f(value: Any) -> float | None:
    return None if value is None else f(value)


def d(value: Any) -> Decimal:
    """Coerce a domain float to ``Decimal`` for storage."""
    if value is None:
        return ZERO
    return Decimal(str(value))


def opt_d(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def dt(value: Any) -> datetime | None:
    """Ensure a datetime is timezone-aware before it is compared or stored."""
    if value is None:
        return None
    from datetime import timezone as _tz

    if value.tzinfo is None:
        return value.replace(tzinfo=_tz.utc)
    return value


# ── market ──────────────────────────────────────────────────────────────


def candle_to_row(candle: Candle) -> dict[str, Any]:
    return {
        "symbol": candle.symbol,
        "timeframe": candle.timeframe.value,
        "timestamp": dt(candle.timestamp),
        "open": d(candle.open),
        "high": d(candle.high),
        "low": d(candle.low),
        "close": d(candle.close),
        "volume": d(candle.volume),
    }


def row_to_candle(row: Any) -> Candle:
    return Candle(
        symbol=row.symbol,
        timeframe=Timeframe(row.timeframe),
        timestamp=dt(row.timestamp),
        open=f(row.open),
        high=f(row.high),
        low=f(row.low),
        close=f(row.close),
        volume=f(row.volume),
    )


# ── signals ─────────────────────────────────────────────────────────────


def signal_to_row(signal: Signal, signal_id: str | None = None) -> dict[str, Any]:
    return {
        "id": signal_id,
        "symbol": signal.symbol,
        "timeframe": signal.timeframe.value,
        "strategy": signal.strategy,
        "strategy_version": signal.strategy_version,
        "action": signal.action.value,
        "confidence": d(signal.confidence),
        "entry": d(signal.entry),
        "stop_loss": opt_d(signal.stop_loss),
        "take_profit": opt_d(signal.take_profit),
        "atr": opt_d(signal.atr),
        "score": signal.score.model_dump() if signal.score else None,
        "rationale": [r.model_dump() for r in signal.rationale] or None,
        "created_at": dt(signal.created_at),
    }


def row_to_signal(row: Any) -> Signal:
    from src.schemas.signal import Rationale, SignalScore

    return Signal(
        symbol=row.symbol,
        timeframe=Timeframe(row.timeframe),
        strategy=row.strategy,
        strategy_version=row.strategy_version,
        action=SignalAction(row.action),
        confidence=f(row.confidence),
        entry=f(row.entry),
        stop_loss=opt_f(row.stop_loss),
        take_profit=opt_f(row.take_profit),
        atr=opt_f(row.atr),
        score=SignalScore(**row.score) if row.score else None,
        rationale=[Rationale(**r) for r in (row.rationale or [])],
        created_at=dt(row.created_at),
    )


# ── orders ──────────────────────────────────────────────────────────────


def order_to_row(order: OrderSchema) -> dict[str, Any]:
    return {
        "id": order.id,
        "client_order_id": order.client_order_id,
        "signal_id": None,
        "symbol": order.symbol,
        "side": order.side.value,
        "order_type": order.order_type.value,
        "status": order.status,
        "mode": order.mode.value,
        "quantity": d(order.quantity),
        "filled_quantity": d(order.filled_quantity),
        "limit_price": opt_d(order.price),
        "average_price": opt_d(order.average_price),
        "fee_usd": d(order.fee_usd),
        "stop_loss": opt_d(order.stop_loss),
        "take_profit": opt_d(order.take_profit),
        "strategy": order.strategy,
        # OrderRequest carries leverage; a persisted Order does not, so it is
        # recorded as 1 (spot) unless the executor sets it explicitly.
        "leverage": d(getattr(order, "leverage", 1.0)),
        "reject_reason": order.reject_reason,
    }


def row_to_order(row: Any) -> OrderSchema:
    return OrderSchema(
        id=row.id,
        client_order_id=row.client_order_id,
        symbol=row.symbol,
        side=OrderSide(row.side),
        order_type=row.order_type,
        status=row.status,
        quantity=f(row.quantity),
        filled_quantity=f(row.filled_quantity),
        price=opt_f(row.limit_price),
        average_price=opt_f(row.average_price),
        fee_usd=f(row.fee_usd),
        stop_loss=opt_f(row.stop_loss),
        take_profit=opt_f(row.take_profit),
        mode=TradingMode(row.mode),
        strategy=row.strategy,
        signal_id=row.signal_id,
        reject_reason=row.reject_reason,
        created_at=dt(row.created_at),
        updated_at=dt(row.updated_at),
    )


# ── trades ──────────────────────────────────────────────────────────────


def trade_to_row(trade: TradeSchema) -> dict[str, Any]:
    return {
        "id": trade.id,
        "order_id": None,
        "signal_id": None,
        "symbol": trade.symbol,
        "side": trade.side.value,
        "strategy": trade.strategy,
        "mode": trade.mode.value,
        "quantity": d(trade.quantity),
        "entry_price": d(trade.entry_price),
        "exit_price": opt_d(trade.exit_price),
        "entry_time": dt(trade.entry_time),
        "exit_time": dt(trade.exit_time),
        "gross_pnl_usd": d(trade.gross_pnl_usd),
        "fees_usd": d(trade.fees_usd),
        "pnl_usd": d(trade.pnl_usd),
        "pnl_pct": d(trade.pnl_pct),
        "initial_risk_per_unit": opt_d(trade.initial_risk_per_unit),
        "risk_multiple": opt_d(trade.risk_multiple),
        "planned_risk_reward": opt_d(trade.planned_risk_reward),
        "exit_reason": trade.exit_reason,
        "notes": trade.notes,
        "is_open": trade.exit_time is None,
    }


def row_to_trade(row: Any) -> TradeSchema:
    return TradeSchema(
        id=row.id,
        order_id=row.order_id or "",
        symbol=row.symbol,
        side=OrderSide(row.side),
        strategy=row.strategy,
        quantity=f(row.quantity),
        entry_price=f(row.entry_price),
        exit_price=opt_f(row.exit_price),
        entry_time=dt(row.entry_time),
        exit_time=dt(row.exit_time),
        gross_pnl_usd=f(row.gross_pnl_usd),
        fees_usd=f(row.fees_usd),
        pnl_usd=f(row.pnl_usd),
        pnl_pct=f(row.pnl_pct),
        initial_risk_per_unit=opt_f(row.initial_risk_per_unit),
        risk_multiple=opt_f(row.risk_multiple),
        planned_risk_reward=opt_f(row.planned_risk_reward),
        exit_reason=row.exit_reason,
        mode=TradingMode(row.mode),
        notes=row.notes,
    )


# ── portfolio ───────────────────────────────────────────────────────────


def position_to_row(position: Position) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "mode": position.mode.value,
        "side": position.side.value,
        "quantity": d(position.quantity),
        "entry_price": d(position.entry_price),
        "current_price": opt_d(position.current_price),
        "stop_loss": opt_d(position.stop_loss),
        "take_profit": opt_d(position.take_profit),
        "strategy": position.strategy,
        "entry_fee_usd": d(position.entry_fee_usd),
        "opened_at": dt(position.opened_at),
    }


def row_to_position(row: Any) -> Position:
    return Position(
        symbol=row.symbol,
        side=OrderSide(row.side),
        quantity=f(row.quantity),
        entry_price=f(row.entry_price),
        current_price=opt_f(row.current_price),
        stop_loss=opt_f(row.stop_loss),
        take_profit=opt_f(row.take_profit),
        strategy=row.strategy,
        mode=TradingMode(row.mode),
        entry_fee_usd=f(row.entry_fee_usd),
        opened_at=dt(row.opened_at),
    )


def balance_to_row(balance: Balance, mode: str) -> dict[str, Any]:
    return {
        "asset": balance.asset,
        "mode": mode,
        "free": d(balance.free),
        "locked": d(balance.locked),
    }


def snapshot_to_row(snapshot: PortfolioSnapshot) -> dict[str, Any]:
    return {
        "mode": snapshot.mode.value,
        "equity_usd": d(snapshot.equity_usd),
        "cash_usd": d(snapshot.cash_usd),
        "positions_value_usd": d(snapshot.positions_value_usd),
        "unrealized_pnl_usd": d(snapshot.unrealized_pnl_usd),
        "realized_pnl_usd": d(snapshot.realized_pnl_usd),
        "daily_pnl_usd": d(snapshot.daily_pnl_usd),
        "total_exposure_usd": d(snapshot.total_exposure_usd),
        "exposure_pct": d(snapshot.exposure_pct),
        "open_positions": snapshot.open_positions,
        "current_drawdown_pct": d(snapshot.current_drawdown_pct),
        "peak_equity_usd": d(snapshot.peak_equity_usd),
        "positions": [p.model_dump(mode="json") for p in snapshot.positions] or None,
        "as_of": dt(snapshot.as_of),
    }


def row_to_snapshot(row: Any) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity_usd=f(row.equity_usd),
        cash_usd=f(row.cash_usd),
        positions_value_usd=f(row.positions_value_usd),
        unrealized_pnl_usd=f(row.unrealized_pnl_usd),
        realized_pnl_usd=f(row.realized_pnl_usd),
        daily_pnl_usd=f(row.daily_pnl_usd),
        total_exposure_usd=f(row.total_exposure_usd),
        exposure_pct=f(row.exposure_pct),
        open_positions=row.open_positions,
        current_drawdown_pct=f(row.current_drawdown_pct),
        peak_equity_usd=f(row.peak_equity_usd),
        mode=TradingMode(row.mode),
        as_of=dt(row.as_of),
        positions=[Position(**p) for p in (row.positions or [])],
    )


# ── risk ────────────────────────────────────────────────────────────────


def assessment_to_row(
    assessment: RiskAssessment,
    *,
    symbol: str,
    side: str,
    mode: str,
    requested_quantity: float,
    order_id: str | None = None,
    signal_id: str | None = None,
    strategy: str | None = None,
    equity: float | None = None,
    drawdown: float | None = None,
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "signal_id": signal_id,
        "symbol": symbol,
        "side": side,
        "mode": mode,
        "strategy": strategy,
        "verdict": assessment.verdict.value,
        "risk_level": assessment.risk_level.value,
        "requested_quantity": d(requested_quantity),
        "approved_quantity": d(assessment.approved_quantity),
        "approved_notional_usd": d(assessment.approved_notional_usd),
        "approved_risk_usd": d(assessment.approved_risk_usd),
        "requires_approval": assessment.requires_approval,
        "leverage": d(assessment.leverage),
        "checks": [c.model_dump(mode="json") for c in assessment.checks],
        "equity_at_assessment": opt_d(equity),
        "drawdown_at_assessment": opt_d(drawdown),
        "assessed_at": dt(assessment.assessed_at),
        "engine_version": assessment.engine_version,
    }


def risk_events_from_assessment(
    assessment: RiskAssessment, assessment_id: str
) -> list[dict[str, Any]]:
    """One event row per check, pass or fail.

    Failed-only would be far smaller, but then "what did the system check?" has
    no answer for an order that was approved.
    """
    return [
        {
            "assessment_id": assessment_id,
            "rule": str(check.rule),
            "severity": check.severity.value,
            "passed": check.passed,
            "symbol": None,
            "message": check.message,
            "observed": check.observed,
            "limit_value": check.limit,
            "unit": check.unit,
            "context": None,
            "created_at": dt(assessment.assessed_at),
        }
        for check in assessment.checks
    ]