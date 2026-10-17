"""Exponential moving average."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def ema(values: object, period: int = 20) -> NDArray[np.float64]:
    """Exponential moving average, seeded with the first SMA(period).

    The SMA seeding matters: an EMA seeded with the first raw value produces
    different numbers than every charting platform shows, which would make our
    own indicators disagree with the TradingView alerts that feed the system.
    """
    series = np.asarray(values, dtype=np.float64)
    if series.ndim != 1:
        raise ValueError(f"expected a 1-D series, got shape {series.shape}")
    if series.size < period:
        raise ValueError(f"EMA({period}) needs at least {period} values, got {series.size}")

    output = np.full(series.size, np.nan)
    alpha = 2.0 / (period + 1.0)
    output[period - 1] = series[:period].mean()
    for index in range(period, series.size):
        output[index] = alpha * series[index] + (1 - alpha) * output[index - 1]
    return output
