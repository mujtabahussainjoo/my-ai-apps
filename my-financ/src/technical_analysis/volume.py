"""Volume analysis: relative volume, OBV, and volume-price divergence."""

from __future__ import annotations

import numpy as np

from src.core.constants import VOLUME_MA_PERIOD
from src.technical_analysis.indicators.base import FloatArray, _as_array, sma


def volume_ratio(volume: object, period: int = VOLUME_MA_PERIOD) -> FloatArray:
    """Current volume divided by its moving average.

    Values > 1 mean above-average participation, which is the minimum
    confirmation a momentum entry should require.
    """
    volume_a = _as_array(volume)
    if volume_a.size < period:
        raise ValueError(f"volume_ratio needs at least {period} bars, got {volume_a.size}")
    average = sma(volume_a, period)
    output = np.full(volume_a.size, np.nan)
    valid = ~np.isnan(average) & (average > 0)
    output[valid] = volume_a[valid] / average[valid]
    return output


def on_balance_volume(close: object, volume: object) -> FloatArray:
    """Cumulative signed volume. Rising OBV with rising price confirms a trend."""
    close_a, volume_a = _as_array(close), _as_array(volume)
    if close_a.size != volume_a.size:
        raise ValueError("close and volume must be the same length")
    direction = np.sign(np.diff(close_a, prepend=close_a[0]))
    return np.cumsum(direction * volume_a)


def is_volume_confirming(ratio: float | None, minimum: float = 1.2) -> bool:
    """Above-average volume — required for a momentum entry to be credible."""
    return bool(ratio is not None and np.isfinite(ratio) and ratio >= minimum)


def is_volume_weak(ratio: float | None, maximum: float = 0.8) -> bool:
    return bool(ratio is not None and np.isfinite(ratio) and ratio <= maximum)


def volume_trend(volume: object, lookback: int = 10) -> float | None:
    """Percent change in mean volume between the last two windows."""
    volume_a = _as_array(volume)
    if volume_a.size < lookback * 2:
        return None
    recent = volume_a[-lookback:].mean()
    prior = volume_a[-lookback * 2 : -lookback].mean()
    if prior <= 0:
        return None
    return (recent - prior) / prior * 100