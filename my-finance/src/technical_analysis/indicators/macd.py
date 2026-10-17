"""Moving Average Convergence Divergence."""

from __future__ import annotations

import numpy as np

from src.core.constants import MACD_FAST, MACD_SIGNAL, MACD_SLOW
from src.technical_analysis.indicators.base import FloatArray, _as_array, ema


def macd_line(values: object, fast: int = MACD_FAST, slow: int = MACD_SLOW) -> FloatArray:
    """MACD line = EMA(fast) - EMA(slow)."""
    series = _as_array(values)
    fast_ema, slow_ema = ema(series, fast), ema(series, slow)
    output = np.full(series.size, np.nan)
    valid = ~np.isnan(fast_ema) & ~np.isnan(slow_ema)
    output[valid] = fast_ema[valid] - slow_ema[valid]
    return output


def signal_line(values: object, period: int = MACD_SIGNAL) -> FloatArray:
    """EMA of the MACD line, ignoring the nan warm-up region."""
    series = _as_array(values)
    output = np.full(series.size, np.nan)
    valid = ~np.isnan(series)
    if not valid.any():
        return output
    first_valid = int(np.argmax(valid))
    tail = series[first_valid:]
    tail_signal = ema(tail, period)
    output[first_valid:] = tail_signal
    return output


def histogram(values: object, signal_period: int = MACD_SIGNAL) -> FloatArray:
    """MACD - signal. Rising/falling histogram indicates momentum change."""
    line = macd_line(values)
    signal = signal_line(line, signal_period)
    output = np.full(line.size, np.nan)
    valid = ~np.isnan(line) & ~np.isnan(signal)
    output[valid] = line[valid] - signal[valid]
    return output


def compute(
    values: object,
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal_period: int = MACD_SIGNAL,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Return ``(macd, signal, histogram)`` aligned to the input length."""
    series = _as_array(values)
    line = macd_line(series, fast, slow)
    signal = signal_line(line, signal_period)
    hist = np.full(line.size, np.nan)
    valid = ~np.isnan(line) & ~np.isnan(signal)
    hist[valid] = line[valid] - signal[valid]
    return line, signal, hist


def is_bullish_crossover(line: FloatArray, signal: FloatArray) -> bool:
    """True only on the bar where the lines actually crossed, not while above."""
    if line.size < 2 or signal.size < 2:
        return False
    now, prev = line[-1] - signal[-1], line[-2] - signal[-2]
    return bool(np.isfinite(now) and np.isfinite(prev) and prev <= 0 < now)


def is_bearish_crossover(line: FloatArray, signal: FloatArray) -> bool:
    if line.size < 2 or signal.size < 2:
        return False
    now, prev = line[-1] - signal[-1], line[-2] - signal[-2]
    return bool(np.isfinite(now) and np.isfinite(prev) and prev >= 0 > now)
