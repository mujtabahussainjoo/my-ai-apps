"""Simple moving average."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def sma(values: object, period: int = 20) -> NDArray[np.float64]:
    """Simple moving average over a rolling window.

    Computed with a cumulative sum so cost is O(n) rather than O(n * period),
    which matters because the backtester calls this on every bar of every
    strategy run.
    """
    series = np.asarray(values, dtype=np.float64)
    if series.ndim != 1:
        raise ValueError(f"expected a 1-D series, got shape {series.shape}")
    if series.size < period:
        raise ValueError(f"SMA({period}) needs at least {period} values, got {series.size}")

    output = np.full(series.size, np.nan)
    cumulative = np.cumsum(np.insert(series, 0, 0.0))
    output[period - 1 :] = (cumulative[period:] - cumulative[:-period]) / period
    return output
