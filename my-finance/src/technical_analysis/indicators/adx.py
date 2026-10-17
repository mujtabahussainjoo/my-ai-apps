"""Average Directional Index — trend strength regardless of direction."""

from __future__ import annotations

import numpy as np

from src.core.constants import ADX_PERIOD
from src.technical_analysis.indicators.base import FloatArray, _as_array, wilder_smooth


def directional_movement(high: object, low: object) -> tuple[FloatArray, FloatArray]:
    """Return ``(plus_dm, minus_dm)``."""
    high_a, low_a = _as_array(high), _as_array(low)
    if high_a.size != low_a.size:
        raise ValueError("high and low must be the same length")

    up_move = np.diff(high_a, prepend=high_a[0])
    down_move = -np.diff(low_a, prepend=low_a[0])
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    return plus_dm, minus_dm


def adx(
    high: object,
    low: object,
    close: object,
    period: int = ADX_PERIOD,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Return ``(adx, plus_di, minus_di)``.

    ADX above ~25 indicates a trending market; below ~20 indicates ranging.
    Only ``plus_di`` vs ``minus_di`` tells you the direction.
    """
    high_a, low_a, close_a = _as_array(high), _as_array(low), _as_array(close)
    if not (high_a.size == low_a.size == close_a.size):
        raise ValueError("high, low and close must be the same length")
    if high_a.size < period * 2:
        raise ValueError(f"ADX({period}) needs at least {period * 2} bars, got {high_a.size}")

    plus_dm, minus_dm = directional_movement(high_a, low_a)

    prev_close = np.roll(close_a, 1)
    prev_close[0] = close_a[0]
    true_range = np.maximum(
        high_a - low_a,
        np.maximum(np.abs(high_a - prev_close), np.abs(low_a - prev_close)),
    )

    atr_values = np.full(high_a.size, np.nan)
    atr_values[period:] = wilder_smooth(true_range[period:], period)

    smooth_plus = np.full(high_a.size, np.nan)
    smooth_minus = np.full(high_a.size, np.nan)
    smooth_plus[period:] = wilder_smooth(plus_dm[period:], period)
    smooth_minus[period:] = wilder_smooth(minus_dm[period:], period)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * np.divide(
            smooth_plus, atr_values, out=np.zeros_like(smooth_plus), where=atr_values > 0
        )
        minus_di = 100 * np.divide(
            smooth_minus, atr_values, out=np.zeros_like(smooth_minus), where=atr_values > 0
        )
        di_sum = plus_di + minus_di
        dx = 100 * np.divide(
            np.abs(plus_di - minus_di),
            di_sum,
            out=np.zeros_like(di_sum),
            where=di_sum > 0,
        )

    adx_values = np.full(high_a.size, np.nan)
    valid_dx = ~np.isnan(dx)
    if valid_dx.sum() >= period:
        first = int(np.argmax(valid_dx))
        smoothed = wilder_smooth(dx[first:], period)
        adx_values[first:] = smoothed
    return adx_values, plus_di, minus_di


def is_trending(adx_value: float, threshold: float = 25.0) -> bool:
    return bool(np.isfinite(adx_value) and adx_value > threshold)


def is_ranging(adx_value: float, threshold: float = 20.0) -> bool:
    return bool(np.isfinite(adx_value) and adx_value < threshold)
