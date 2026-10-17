"""Support and resistance from confirmed swing pivots.

Uses a fractal/pivot definition rather than round numbers: a level only counts
once price has actually respected it. Round-number heuristics are avoided
because they produce levels that look precise but have no structural meaning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.technical_analysis.indicators.base import FloatArray, _as_array


@dataclass(frozen=True, slots=True)
class SupportResistance:
    support: float | None
    resistance: float | None
    pivot_highs: FloatArray
    pivot_lows: FloatArray

    @property
    def mid_level(self) -> float | None:
        if self.support is None or self.resistance is None:
            return None
        return (self.support + self.resistance) / 2

    def distance_to_support_pct(self, price: float) -> float | None:
        if self.support is None or price <= 0:
            return None
        return (price - self.support) / price * 100

    def distance_to_resistance_pct(self, price: float) -> float | None:
        if self.resistance is None or price <= 0:
            return None
        return (self.resistance - price) / price * 100


def find_pivots(
    values: object,
    left: int = 3,
    right: int = 3,
) -> tuple[FloatArray, FloatArray]:
    """Locate fractal pivots.

    A pivot needs ``right`` bars of confirmation, so the last ``right`` bars
    cannot contain confirmed pivots. ``find_pivots`` must therefore be called
    with the array truncated by ``right`` when checking "did a breakout just
    happen", otherwise the breakout is undetectable by construction.
    """
    series = _as_array(values)
    highs = np.full(series.size, np.nan)
    lows = np.full(series.size, np.nan)
    if series.size < left + right + 1:
        return highs, lows

    for index in range(left, series.size - right):
        window = series[index - left : index + right + 1]
        centre = series[index]
        if centre == window.max() and (window == centre).sum() == 1:
            highs[index] = centre
        if centre == window.min() and (window == centre).sum() == 1:
            lows[index] = centre
    return highs, lows


def cluster_levels(pivots: FloatArray, tolerance_pct: float = 0.5) -> list[float]:
    """Merge nearby pivots into single levels, strongest (most touches) first."""
    finite = pivots[np.isfinite(pivots)]
    if finite.size == 0:
        return []
    ordered = np.sort(finite)
    clusters: list[list[float]] = [[float(ordered[0])]]
    for value in ordered[1:]:
        anchor = np.mean(clusters[-1])
        if abs(value - anchor) / anchor * 100 <= tolerance_pct:
            clusters[-1].append(float(value))
        else:
            clusters.append([float(value)])

    ranked = sorted(clusters, key=len, reverse=True)
    return [float(np.mean(cluster)) for cluster in ranked]


def detect(
    high: object,
    low: object,
    close: object,
    *,
    left: int = 3,
    right: int = 3,
    lookback: int = 200,
    tolerance_pct: float = 0.5,
    max_levels: int = 5,
) -> SupportResistance:
    """Derive nearest support below price and nearest resistance above it."""
    high_a, low_a, close_a = _as_array(high), _as_array(low), _as_array(close)
    window = slice(-min(lookback, high_a.size), None)
    price = float(close_a[-1])

    # `find_pivots` returns both kinds of pivot from one series, so each kind
    # must be taken from the series it actually describes: resistance from
    # swing highs, support from swing lows. Deriving both from the highs would
    # invent support levels out of resistance.
    pivot_highs, _ = find_pivots(high_a[window], left, right)
    _, pivot_lows = find_pivots(low_a[window], left, right)
    pivot_highs_all, _ = find_pivots(high_a, left, right)
    _, pivot_lows_all = find_pivots(low_a, left, right)

    resistances = [lvl for lvl in cluster_levels(pivot_highs, tolerance_pct) if lvl > price]
    supports = [lvl for lvl in cluster_levels(pivot_lows, tolerance_pct) if lvl < price]

    return SupportResistance(
        # The *nearest* level below price is the highest qualifying support;
        # taking the minimum would report the level furthest away, which is the
        # one least likely to be respected.
        support=max(supports) if supports else None,
        resistance=min(resistances) if resistances else None,
        pivot_highs=pivot_highs_all,
        pivot_lows=pivot_lows_all,
    )


def is_near_support(price: float, level: float | None, within_pct: float = 1.0) -> bool:
    if level is None or price <= 0:
        return False
    return abs(price - level) / price * 100 <= within_pct


def is_near_resistance(price: float, level: float | None, within_pct: float = 1.0) -> bool:
    return is_near_support(price, level, within_pct)
