"""Relative Strength Index."""

from __future__ import annotations

import numpy as np

from src.core.constants import RSI_OVERBOUGHT, RSI_OVERSOLD
from src.technical_analysis.indicators.base import FloatArray, _as_array, wilder_smooth


def rsi(values: object, period: int = 14) -> FloatArray:
    """Wilder's RSI on closing prices.

    Uses Wilder smoothing rather than a simple average of gains/losses, which
    is the definition RSI is actually specified with.
    """
    series = _as_array(values)
    if series.size < period + 1:
        raise ValueError(f"RSI({period}) needs at least {period + 1} closes, got {series.size}")

    delta = np.diff(series, prepend=series[0])
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    # The first delta is synthetic (zero) and must not enter the average.
    gains[0] = np.nan
    losses[0] = np.nan

    avg_gain = wilder_smooth(gains[1:], period)
    avg_loss = wilder_smooth(losses[1:], period)

    # Wilder's average is undefined until the smoothing window fills. Those
    # bars must stay nan: reporting 100 there would read as "overbought" and
    # make a strategy reject every entry during warm-up.
    valid = ~np.isnan(avg_gain) & ~np.isnan(avg_loss)
    safe_loss = np.where(avg_loss > 0, avg_loss, 1.0)
    rs = np.divide(
        avg_gain,
        safe_loss,
        out=np.full_like(avg_gain, np.inf),
        where=valid & (avg_loss > 0),
    )
    computed = 100.0 - (100.0 / (1.0 + rs))
    # Zero average loss means an unbroken advance -> RSI 100 by definition.
    computed[valid & (avg_loss <= 0)] = 100.0
    computed[~valid] = np.nan

    output = np.full(series.size, np.nan)
    output[1:] = computed
    return np.clip(output, 0.0, 100.0)


def rsi_state(value: float) -> str:
    if np.isnan(value):
        return "unknown"
    if value <= RSI_OVERSOLD:
        return "oversold"
    if value >= RSI_OVERBOUGHT:
        return "overbought"
    return "neutral"


def is_oversold(value: float, threshold: float = RSI_OVERSOLD) -> bool:
    return not np.isnan(value) and value <= threshold


def is_overbought(value: float, threshold: float = RSI_OVERBOUGHT) -> bool:
    return not np.isnan(value) and value >= threshold
