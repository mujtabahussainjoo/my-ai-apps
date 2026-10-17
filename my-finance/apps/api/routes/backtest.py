"""Backtest submission and results.

A backtest runs synchronously here because runs are bounded (bar counts are
capped) and the alternative - queueing work the API has no worker for yet -
would make the endpoint look functional while doing nothing.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from src.core.enums import Timeframe
from src.core.logging import get_logger
from src.strategies import registry as strategy_registry

from apps.api.dependencies import ApiKeyDep, BacktestsDep, SessionDep, SettingsDep

logger = get_logger(__name__)
router = APIRouter(prefix="/backtest", tags=["backtest"])

#: Hard ceiling on bar count. A request for more is a mistake or an attempt to
#: make the API a denial-of-service tool against itself.
MAX_BARS = 50_000


class BacktestRequest(BaseModel):
    strategy: str = Field(..., description="Strategy name")
    symbol: str = Field("BTC/USDT", description="Symbol to test on")
    timeframe: str = Field("1h", description="Candle timeframe")
    bars: int = Field(1500, ge=300, le=MAX_BARS, description="Bars to simulate")
    source: str = Field(
        "binance",
        description="Where candles come from: 'binance' fetches real history, "
        "'synthetic' generates a deterministic series",
    )
    evaluation: bool = False
    initial_capital: float = Field(10_000.0, gt=0.0, le=1_000_000.0)


@router.post("")
def run_backtest(
    body: BacktestRequest,
    auth: ApiKeyDep,
    backtests: BacktestsDep,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Run a backtest and persist the result."""
    if body.strategy not in strategy_registry.all_names():
        raise HTTPException(
            status_code=404,
            detail=(f"unknown strategy {body.strategy!r}; known: {', '.join(strategy_registry.all_names())}"),
        )

    from src.backtesting.engine import BacktestConfig, BacktestEngine

    try:
        timeframe = Timeframe(body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"unknown timeframe {body.timeframe!r}") from exc

    if body.source not in ("binance", "synthetic"):
        raise HTTPException(status_code=422, detail="source must be 'binance' or 'synthetic'")

    # Fetching is async; a fresh loop per request is fine here because each
    # request builds and closes its own collector.
    try:
        candles = asyncio.run(_fetch_candles(body.source, body.symbol, timeframe, body.bars))
    except Exception as exc:  # noqa: BLE001
        logger.exception("backtest_fetch_failed", source=body.source)
        raise HTTPException(
            status_code=502, detail=f"could not load candles: {type(exc).__name__}: {exc}"
        ) from exc

    if len(candles) < 300:
        raise HTTPException(
            status_code=422,
            detail=f"only {len(candles)} candles available; at least 300 are needed",
        )

    config = BacktestConfig(
        strategy=body.strategy,
        symbol=body.symbol,
        timeframe=timeframe,
        starting_equity=body.initial_capital,
    )

    try:
        if body.evaluation:
            from src.backtesting.walk_forward import evaluate_split

            training, held_out, evaluation_id = evaluate_split(candles, config, settings=settings)
            for output in (training, held_out):
                saved = backtests.save(output, source=body.source, bar_count=output.bars_processed)
                saved.config = {**saved.config, "evaluation_id": evaluation_id}
            session.commit()
            return {
                "evaluation_id": evaluation_id,
                "in_sample": _serialise(training, training.run_id),
                "out_of_sample": _serialise(held_out, held_out.run_id),
            }
        result = BacktestEngine(settings).run(candles, config)
    except Exception as exc:  # noqa: BLE001 - report rather than 500 blindly
        session.rollback()
        logger.exception("backtest_failed", strategy=body.strategy)
        raise HTTPException(status_code=422, detail=f"backtest failed: {type(exc).__name__}: {exc}") from exc

    row = backtests.save(result, source=body.source, bar_count=len(candles))
    session.commit()
    return _serialise(result, run_id=row.run_id)


@router.get("")
def list_runs(
    backtests: BacktestsDep,
    strategy: str | None = None,
    limit: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    rows = backtests.list_runs(strategy=strategy, limit=limit)
    return {
        "count": len(rows),
        "runs": [
            {
                "run_id": r.run_id,
                "strategy": r.strategy,
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "source": r.source,
                "trade_count": r.trade_count,
                "signals_generated": r.signals_generated,
                "bar_count": r.bar_count,
                **_headline(r.metrics),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in rows
        ],
    }


@router.get("/{run_id}")
def get_run(run_id: str, backtests: BacktestsDep) -> dict[str, Any]:
    row = backtests.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no backtest run {run_id!r}")
    return {
        "run_id": row.run_id,
        "strategy": row.strategy,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "source": row.source,
        "config": row.config,
        "metrics": row.metrics,
        "starting_equity": float(row.starting_equity or 0.0),
        "equity_curve": row.equity_curve,
        "signals_generated": row.signals_generated,
        "trade_count": row.trade_count,
        "bar_count": row.bar_count,
        **_headline(row.metrics),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.get("/{run_id}/trades")
def get_run_trades(run_id: str, backtests: BacktestsDep) -> dict[str, Any]:
    if backtests.get(run_id) is None:
        raise HTTPException(status_code=404, detail=f"no backtest run {run_id!r}")
    rows = backtests.trades_for(run_id)
    return {
        "run_id": run_id,
        "count": len(rows),
        "trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": float(t.quantity or 0.0),
                "entry_price": float(t.entry_price or 0.0),
                "exit_price": float(t.exit_price or 0.0) if t.exit_price else None,
                "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                "gross_pnl_usd": float(t.gross_pnl_usd or 0.0),
                "fees_usd": float(t.fees_usd or 0.0),
                "pnl_usd": float(t.pnl_usd or 0.0),
                "risk_multiple": float(t.risk_multiple or 0.0) if t.risk_multiple else None,
                "exit_reason": t.exit_reason,
            }
            for t in rows
        ],
    }


async def _fetch_candles(source: str, symbol: str, timeframe: Timeframe, bars: int) -> list:
    from src.market_data.collectors.binance import BinanceCollector, SyntheticCollector

    if source == "synthetic":
        return await SyntheticCollector().fetch_historical(symbol, timeframe, max_candles=bars)

    collector = BinanceCollector()
    try:
        return await collector.fetch_historical(symbol, timeframe, max_candles=bars)
    finally:
        # The collector holds a pooled client; leaving it open leaks sockets
        # across repeated API calls.
        await collector.close()


def _headline(metrics: dict | None) -> dict[str, Any]:
    """The few numbers a list view needs, lifted out of the metrics blob."""
    if not metrics:
        return {}
    return {
        "net_profit_pct": metrics.get("net_profit_pct"),
        "net_profit_usd": metrics.get("net_profit_usd"),
        "win_rate": metrics.get("win_rate"),
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "total_trades": metrics.get("total_trades"),
        "profit_factor": metrics.get("profit_factor"),
    }


def _serialise(result: Any, run_id: str) -> dict[str, Any]:
    metrics = result.metrics.model_dump(mode="json") if hasattr(result.metrics, "model_dump") else {}
    return {
        "run_id": run_id,
        "strategy": result.config.strategy,
        "symbol": result.config.symbol,
        "timeframe": result.config.timeframe.value,
        "status": "completed",
        "bars_processed": result.bars_processed,
        "signals_generated": result.signals_generated,
        "signals_rejected_by_risk": result.signals_rejected_by_risk,
        "trades": len(result.trades or []),
        "metrics": metrics,
        **_headline(metrics),
        "equity_curve": result.equity_curve,
        "notes": result.notes,
    }


__all__ = ["router"]
