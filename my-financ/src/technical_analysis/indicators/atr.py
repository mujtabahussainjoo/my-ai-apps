"""Average True Range — the volatility unit used for stops and sizing."""

from __future__ import annotations

import numpy as np

from src.core.constants import ATR_PERIOD
from src.technical_analysis.indicators.base import FloatArray, _as_array, wilder_smooth


def true_range(high: object, low: object, close: object) -> FloatArray:
    """True range: max of today's range, and gaps from yesterday's close."""
    high_a, low_a, close_a = _as_array(high), _as_array(low), _as_array(close)
    if not (high_a.size == low_a.size == close_a.size):
        raise ValueError("high, low and close must be the same length")

    previous_close = np.roll(close_a, 1)
    previous_close[0] = close_a[0]
    ranges = np.maximum(
        high_a - low_a,
        np.maximum(np.abs(high_a - previous_close), np.abs(low_a - previous_close)),
    )
    return ranges


def atr(
    high: object,
    low: object,
    close: object,
    period: int = ATR_PERIOD,
) -> FloatArray:
    """Wilder-smoothed ATR."""
    ranges = true_range(high, low, close)
    if ranges.size < period:
        raise ValueError(f"ATR({period}) needs at least {period} bars, got {ranges.size}")
    output = np.full(ranges.size, np.nan)
    smoothed = wilder_smooth(ranges, period)
    output[period - 1 :] = smoothed[period - 1 :]
    return output


def atr_percent(atr_values: object, close: object) -> FloatArray:
    """ATR expressed as a percentage of price — comparable across symbols."""
    atr_array, close_array = _as_array(atr_values), _as_array(close)
    output = np.full(atr_array.size, np.nan)
    valid = ~np.isnan(atr_array) & (close_array > 0)
    output[valid] = atr_array[valid] / close_array[valid] * 100
    return output


def volatility_stop_distance(
    atr_value: float,
    close: float,
    multiplier: float = 2.0,
    min_pct: float = 0.25,
    max_pct: float = 5.0,
) -> float:
    """Stop distance in percent, clamped to sane bounds.

    Clamping is a guardrail: an ATR-derived stop that lands 20% away on a
    volatile alt is technically "correct" and practically useless, while one
    inside the noise gets triggered immediately.
    """
    if np.isnan(atr_value) or close <= 0:
        return min_pct
    raw_pct = atr_value / close * 100 * multiplier
    return float(min(max(raw_pct, min_pct), max_pct))


def is_high_volatility(atr_pct: float, threshold: float = 3.0) -> bool:
    return bool(np.isfinite(atr_pct) and atr_pct > threshold)