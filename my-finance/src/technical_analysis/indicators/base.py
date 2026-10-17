"""Shared indicator primitives and helpers.

``ema`` and ``sma`` are implemented in their own modules and re-exported here
for convenience, since most callers want them together.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from src.technical_analysis.indicators.ema import ema
from src.technical_analysis.indicators.sma import sma

FloatArray = NDArray[np.float64]

__all__ = [
    "ema",
    "sma",
    "wilder_smooth",
    "stdev",
    "rolling_max",
    "rolling_min",
    "crossover",
    "crossunder",
    "pct_change",
    "FloatArray",
]


def _as_array(values: object) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1:
        raise ValueError(f"expected a 1-D series, got shape {array.shape}")
    return array


def _require_length(values: FloatArray, minimum: int, name: str) -> None:
    if values.size < minimum:
        raise ValueError(f"{name} needs at least {minimum} values, got {values.size}")


def wilder_smooth(values: object, period: int) -> FloatArray:
    """Wilder's smoothing (used by RSI, ATR, ADX).

    Equivalent to an EMA with alpha = 1/period but seeded with an SMA, which
    is the smoothing RSI/ATR are defined with.
    """
    series = _as_array(values)
    _require_length(series, period, f"Wilder({period})")
    output = np.full(series.size, np.nan)
    output[period - 1] = series[:period].mean()
    for index in range(period, series.size):
        output[index] = (output[index - 1] * (period - 1) + series[index]) / period
    return output


def stdev(values: object, period: int) -> FloatArray:
    """Rolling population standard deviation."""
    series = _as_array(values)
    _require_length(series, period, f"stdev({period})")
    output = np.full(series.size, np.nan)
    for index in range(period - 1, series.size):
        output[index] = series[index - period + 1 : index + 1].std()
    return output


def rolling_max(values: object, period: int) -> FloatArray:
    series = _as_array(values)
    _require_length(series, period, f"rolling_max({period})")
    output = np.full(series.size, np.nan)
    for index in range(period - 1, series.size):
        output[index] = series[index - period + 1 : index + 1].max()
    return output


def rolling_min(values: object, period: int) -> FloatArray:
    series = _as_array(values)
    _require_length(series, period, f"rolling_min({period})")
    output = np.full(series.size, np.nan)
    for index in range(period - 1, series.size):
        output[index] = series[index - period + 1 : index + 1].min()
    return output


def crossover(fast: object, slow: object) -> FloatArray:
    """1.0 on bars where ``fast`` crossed *above* ``slow``, else 0.0."""
    fast_array, slow_array = _as_array(fast), _as_array(slow)
    if fast_array.size != slow_array.size:
        raise ValueError("fast and slow series must be the same length")
    above = fast_array > slow_array
    previous = np.roll(above, 1)
    previous[0] = False
    return (above & ~previous).astype(np.float64)


def crossunder(fast: object, slow: object) -> FloatArray:
    """1.0 on bars where ``fast`` crossed *below* ``slow``, else 0.0."""
    return crossover(slow, fast)


def pct_change(values: object, periods: int = 1) -> FloatArray:
    series = _as_array(values)
    output = np.full(series.size, np.nan)
    if periods < series.size:
        output[periods:] = (series[periods:] - series[:-periods]) / series[:-periods] * 100
    return output
