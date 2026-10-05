"""Bollinger Bands."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.core.constants import BOLLINGER_PERIOD, BOLLINGER_STD
from src.technical_analysis.indicators.base import FloatArray, _as_array, sma, stdev


@dataclass(frozen=True, slots=True)
class BollingerBands:
    upper: FloatArray
    middle: FloatArray
    lower: FloatArray
    bandwidth: FloatArray
    percent_b: FloatArray

    @property
    def squeeze(self) -> bool:
        """Bandwidth below 4% indicates compressed volatility.

        A squeeze is a *precondition* for a breakout, not a signal itself.
        """
        latest = self.bandwidth[-1]
        return bool(np.isfinite(latest) and latest < 0.04)


def bollinger(
    values: object,
    period: int = BOLLINGER_PERIOD,
    num_std: float = BOLLINGER_STD,
) -> BollingerBands:
    """Bollinger Bands with bandwidth and %B.

    %B locates price within the bands (0 = lower, 1 = upper), which is more
    informative than the raw distance for mean-reversion logic.
    """
    series = _as_array(values)
    middle = sma(series, period)
    deviation = stdev(series, period) * num_std
    upper, lower = middle + deviation, middle - deviation

    bandwidth = np.full(series.size, np.nan)
    valid_middle = ~np.isnan(middle) & (middle > 0)
    bandwidth[valid_middle] = (
        (upper[valid_middle] - lower[valid_middle]) / middle[valid_middle]
    )

    percent_b = np.full(series.size, np.nan)
    span = upper - lower
    valid_span = np.isfinite(span) & (span > 0)
    percent_b[valid_span] = (series[valid_span] - lower[valid_span]) / span[valid_span]

    return BollingerBands(
        upper=upper,
        middle=middle,
        lower=lower,
        bandwidth=bandwidth,
        percent_b=percent_b,
    )


def is_lower_band_touch(series: FloatArray, bands: BollingerBands) -> bool:
    latest, lower = series[-1], bands.lower[-1]
    return bool(np.isfinite(lower) and latest <= lower)


def is_upper_band_touch(series: FloatArray, bands: BollingerBands) -> bool:
    latest, upper = series[-1], bands.upper[-1]
    return bool(np.isfinite(upper) and latest >= upper)