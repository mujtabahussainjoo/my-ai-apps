"""Trend classification and market-regime detection."""

from __future__ import annotations

import numpy as np

from src.core.enums import MarketRegime, TrendState
from src.technical_analysis.indicators.adx import adx
from src.technical_analysis.indicators.base import FloatArray, _as_array, ema, pct_change


def classify_trend(
    close: object,
    ema_fast: object,
    ema_slow: object,
    adx_value: float | None = None,
) -> TrendState:
    """Grade trend strength from EMA structure, confirmed by ADX strength.

    ADX is used as a *modifier*: EMA structure without ADX confirmation is
    treated as neutral, because a flat market produces EMA crossovers that look
    identical to a real trend.
    """
    close_a = _as_array(close)
    price = float(close_a[-1])
    fast, slow = float(ema_fast[-1]), float(ema_slow[-1])

    if not all(np.isfinite([price, fast, slow])):
        return TrendState.NEUTRAL

    spread_pct = (fast - slow) / slow * 100 if slow > 0 else 0.0
    trending = adx_value is None or not np.isfinite(adx_value) or adx_value > 20

    if fast > slow and price > fast:
        if trending and spread_pct > 0.5 and (adx_value or 0) > 25:
            return TrendState.STRONG_UP
        return TrendState.UP
    if fast < slow and price < fast:
        if trending and spread_pct < -0.5 and (adx_value or 0) > 25:
            return TrendState.STRONG_DOWN
        return TrendState.DOWN
    return TrendState.NEUTRAL


def detect_regime(
    atr_pct: float | None,
    adx_value: float | None,
    trend: TrendState,
    change_24h_pct: float | None = None,
) -> MarketRegime:
    """Classify the market environment.

    High volatility takes precedence: when volatility is extreme, direction is
    noise and the system should size down rather than pick a side.
    """
    if atr_pct is not None and np.isfinite(atr_pct) and atr_pct > 4.0:
        return MarketRegime.HIGH_VOLATILITY
    if trend in (TrendState.UP, TrendState.STRONG_UP):
        return MarketRegime.BULLISH
    if trend in (TrendState.DOWN, TrendState.STRONG_DOWN):
        return MarketRegime.BEARISH
    return MarketRegime.RANGE


def trend_strength_score(adx_value: float | None) -> float:
    """Map ADX to a 0-1 strength score for weighted confluence scoring."""
    if adx_value is None or not np.isfinite(adx_value):
        return 0.0
    return float(min(max((adx_value - 10) / 40, 0.0), 1.0))


def slope_percent(series: FloatArray, lookback: int = 10) -> float | None:
    """Percent change over ``lookback`` bars — a direct trend velocity measure."""
    array = _as_array(series)
    if array.size <= lookback:
        return None
    past, now = float(array[-lookback - 1]), float(array[-1])
    if past <= 0:
        return None
    return (now - past) / past * 100


def compute_trend_features(
    close: object,
    high: object,
    low: object,
    fast_period: int = 20,
    slow_period: int = 50,
    trend_period: int = 200,
) -> dict[str, object]:
    """All trend-related series at once, for the feature engine."""
    close_a = _as_array(close)
    high_a, low_a = _as_array(high), _as_array(low)

    ema_fast, ema_slow = ema(close_a, fast_period), ema(close_a, slow_period)
    ema_long = ema(close_a, trend_period) if close_a.size > trend_period else np.full(close_a.size, np.nan)
    adx_values, plus_di, minus_di = (
        adx(high_a, low_a, close_a) if close_a.size >= 40 else (np.full(close_a.size, np.nan),) * 3
    )

    return {
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_200": ema_long,
        "adx": adx_values,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "trend": classify_trend(close_a, ema_fast, ema_slow, _last(adx_values)),
        "slope_pct": slope_percent(close_a, 10),
        "change_24h_pct": _last(pct_change(close_a, 24)),
    }


def _last(array: FloatArray) -> float | None:
    value = float(array[-1])
    return value if np.isfinite(value) else None
