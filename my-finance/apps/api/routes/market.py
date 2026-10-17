"""Market data reads: candles, tickers, indicators.

Candles are served from the database rather than proxied live, because the
strategies are computed over stored history: what the dashboard shows is what
the trading loop actually saw.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from src.core.enums import Timeframe

from apps.api.dependencies import CandlesDep, SettingsDep

router = APIRouter(prefix="/market", tags=["market"])


def _timeframe(value: str) -> Timeframe:
    try:
        return Timeframe(value)
    except ValueError as exc:
        allowed = ", ".join(t.value for t in Timeframe)
        raise HTTPException(
            status_code=422, detail=f"unknown timeframe {value!r}; expected one of {allowed}"
        ) from exc


@router.get("/symbols")
def list_symbols(settings: SettingsDep) -> dict[str, object]:
    """The symbols this deployment trades."""
    return {
        "symbols": settings.trading_symbols,
        "timeframe": settings.trading_timeframe,
        "strategies": settings.trading_strategies,
    }


@router.get("/candles")
def get_candles(
    candles: CandlesDep,
    symbol: str = Query(..., description="e.g. BTC/USDT"),
    timeframe: str = Query("1h"),
    limit: int = Query(200, ge=1, le=1000),
    order: str = Query("asc", pattern="^(asc|desc)$"),
) -> dict[str, object]:
    """Stored candles, oldest-first unless ``order=desc``."""
    tf = _timeframe(timeframe)
    rows = candles.get_range(symbol, tf, limit=limit, ascending=(order == "asc"))
    return {
        "symbol": symbol,
        "timeframe": tf.value,
        "count": len(rows),
        "stored_count": candles.count(symbol, tf),
        "oldest": rows[0].timestamp.isoformat() if rows else None,
        "newest": rows[-1].timestamp.isoformat() if rows else None,
        "candles": [c.model_dump(mode="json") for c in rows],
    }


@router.get("/indicators")
def get_indicators(
    candles: CandlesDep,
    symbol: str = Query(...),
    timeframe: str = Query("1h"),
    bars: int = Query(300, ge=60, le=1000),
) -> dict[str, object]:
    """Indicator snapshot over stored candles.

    Returns the input series alongside the snapshot so a client can render a
    chart and the values that produced it from one response.
    """
    from src.technical_analysis.feature_engine import compute_features

    tf = _timeframe(timeframe)
    history = candles.get_range(symbol, tf, limit=bars)
    if len(history) < 2:
        raise HTTPException(
            status_code=404,
            detail=(
                f"not enough stored candles for {symbol} {tf.value} "
                f"({len(history)} stored); run the worker or 'make backfill' first"
            ),
        )
    snapshot = compute_features(history)
    return {
        "symbol": symbol,
        "timeframe": tf.value,
        "bars_used": len(history),
        "snapshot": snapshot.model_dump(mode="json"),
        "latest_candle": history[-1].model_dump(mode="json"),
    }


@router.get("/coverage")
def get_coverage(
    candles: CandlesDep,
    settings: SettingsDep,
    timeframe: str = Query("1h"),
) -> dict[str, object]:
    """What history actually exists, including gaps.

    A gap matters: indicators computed across missing bars are wrong, so this
    endpoint exists to make the problem visible rather than surprising.
    """
    tf = _timeframe(timeframe)
    out = []
    for symbol in settings.trading_symbols:
        out.append(
            {
                "symbol": symbol,
                "bars": candles.count(symbol, tf),
                "first": _iso(candles.first_timestamp(symbol, tf)),
                "last": _iso(candles.last_timestamp(symbol, tf)),
                "has_gap": candles.has_gap(symbol, tf),
            }
        )
    return {"timeframe": tf.value, "symbols": out}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


__all__ = ["router"]
