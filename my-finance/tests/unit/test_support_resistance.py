"""Unit tests for support/resistance derivation.

The bugs these guard against were both silent: they produced a plausible number
rather than an error, and nothing downstream consumed support levels yet, so
no backtest result changed when they were found.
"""

from __future__ import annotations

import numpy as np
import pytest
from src.technical_analysis.support_resistance import (
    cluster_levels,
    detect,
    find_pivots,
    is_near_resistance,
    is_near_support,
)


@pytest.fixture
def two_support_levels():
    """Close series with a deep trough at 70 and a shallow shelf at 95, price 100.

    Lows are close - 2, so the qualifying levels are 68 and 93.
    """
    close = np.array([70.0 if i == 20 else 95.0 if i == 41 else 100.0 for i in range(60)])
    return close + 2, close - 2, close


class TestNearestLevel:
    def test_support_is_the_nearest_level_below_price(self, two_support_levels):
        high, low, close = two_support_levels
        sr = detect(high, low, close, left=3, right=3, tolerance_pct=0.5)

        assert sr.support == pytest.approx(93.0)
        assert sr.support > 68.0, "must not report the trough furthest from price"

    def test_resistance_is_the_nearest_level_above_price(self):
        close = np.array([130.0 if i == 25 else 100.0 for i in range(60)])
        sr = detect(close + 2, close - 2, close, left=3, right=3)

        assert sr.resistance == pytest.approx(132.0)
        assert sr.resistance > close[-1]

    def test_no_levels_are_invented_on_a_flat_market(self):
        close = np.full(60, 100.0)
        sr = detect(close + 1, close - 1, close, left=3, right=3)

        assert sr.support is None
        assert sr.resistance is None


class TestSeriesRouting:
    """Resistance must come from highs and support from lows.

    ``find_pivots`` derives both pivot kinds from a single series, so passing
    the high series for both fabricates support out of swing highs.
    """

    def test_support_requires_a_confirmed_low(self):
        rising = np.linspace(100.0, 200.0, 60)
        sr = detect(rising + 2, rising, rising, left=3, right=3)
        assert sr.support is None, "a series with no confirmed low has no support"

    def test_support_tracks_the_low_series(self):
        close = np.array([70.0 if i == 20 else 95.0 if i == 41 else 100.0 for i in range(60)])
        from_highs = detect(close + 2, close + 1, close, left=3, right=3)
        from_lows = detect(close + 2, close - 2, close, left=3, right=3)

        assert from_lows.support == pytest.approx(93.0)
        assert from_highs.support != from_lows.support

    def test_levels_are_ordered_around_price(self):
        n = 120
        t = np.arange(n)
        close = 100.0 + 0.4 * t + 4.0 * np.sin(t / 3.0)
        sr = detect(close + 1.5, close - 1.5, close, left=3, right=3, tolerance_pct=1.0)

        price = float(close[-1])
        assert sr.support is not None and sr.support < price
        assert sr.resistance is None or sr.resistance > price
        assert 0 < sr.distance_to_support_pct(price) < 10.0


class TestPivots:
    def test_trailing_bars_cannot_be_confirmed_pivots(self):
        series = np.array([1.0, 2, 3, 10, 3, 2, 1.0])
        highs, lows = find_pivots(series, left=2, right=2)

        assert highs[3] == 10.0
        assert np.isnan(highs[-2:]).all(), "unconfirmed bars must stay NaN"

    def test_a_monotonic_rise_confirms_no_low(self):
        series = np.linspace(100.0, 200.0, 40)
        _, lows = find_pivots(series, left=3, right=3)
        assert np.isfinite(lows).sum() == 0

    def test_clustering_merges_nearby_pivots(self):
        pivots = np.array([100.0, 100.3, 99.8, 120.0, np.nan])
        levels = cluster_levels(pivots, tolerance_pct=0.5)

        assert len(levels) == 2
        assert min(levels) == pytest.approx(100.03, abs=0.05)
        assert max(levels) == pytest.approx(120.0)

    def test_empty_pivots_yield_no_levels(self):
        assert cluster_levels(np.array([np.nan, np.nan])) == []


class TestProximity:
    def test_proximity_bounds(self):
        assert is_near_support(100.0, 99.5, within_pct=1.0)
        assert not is_near_support(100.0, 95.0, within_pct=1.0)
        assert is_near_resistance(100.0, 100.4, within_pct=1.0)

    def test_missing_levels_are_never_near(self):
        assert not is_near_support(100.0, None)
        assert not is_near_resistance(100.0, None)
