"""Geometry invariants for generated signals.

Every signal must place its stop and target on the sides its direction requires:

    BUY:  stop < entry < target
    SELL: target < entry < stop

Violating this is not a small error. The backtest engine fills a take-profit
when price touches the target, so a short with a target *above* entry is exited
at a loss and labelled a winner. That single inversion turned a random-walk
backtest into a 9% win rate and a 98% drawdown before it was caught.
"""

from __future__ import annotations

import pytest
from src.core.enums import SignalAction
from src.strategies.base import Strategy


class _Stub(Strategy):
    """Concrete shell: the level builders under test need no market view."""

    name = "stub"
    supports_short = True

    def evaluate(self, context):  # pragma: no cover - not exercised here
        return None


@pytest.fixture
def strategy() -> Strategy:
    return _Stub()


class TestTakeProfitPlacement:
    def test_buy_target_is_above_entry(self, strategy):
        # risk = 2, reward multiple 2 -> 4 points above entry.
        target = strategy.build_take_profit(100.0, 98.0, 2.0, SignalAction.BUY)
        assert target == pytest.approx(104.0)

    def test_sell_target_is_below_entry(self, strategy):
        """The regression: a short's target must be reachable in its direction."""
        target = strategy.build_take_profit(100.0, 102.0, 2.0, SignalAction.SELL)
        assert target == pytest.approx(96.0)
        assert target < 100.0

    def test_target_offset_is_the_reward_multiple(self, strategy):
        for side, stop in ((SignalAction.BUY, 98.0), (SignalAction.SELL, 102.0)):
            for multiple in (1.0, 2.0, 3.5):
                target = strategy.build_take_profit(100.0, stop, multiple, side)
                risk = abs(100.0 - stop)
                assert abs(target - 100.0) == pytest.approx(risk * multiple)

    def test_default_side_is_long(self, strategy):
        assert strategy.build_take_profit(100.0, 98.0, 2.0) > 100.0


class TestStopPlacement:
    def test_buy_stop_is_below_entry(self, strategy):
        assert strategy.build_stop_loss(100.0, SignalAction.BUY, None, fallback_pct=2.0) < 100.0

    def test_sell_stop_is_above_entry(self, strategy):
        assert strategy.build_stop_loss(100.0, SignalAction.SELL, None, fallback_pct=2.0) > 100.0

    def test_atr_widens_the_stop_but_keeps_the_side(self, strategy):
        long_stop = strategy.build_stop_loss(100.0, SignalAction.BUY, atr=2.0)
        short_stop = strategy.build_stop_loss(100.0, SignalAction.SELL, atr=2.0)
        assert long_stop < 100.0
        assert short_stop > 100.0


class TestOrderingPredicate:
    @pytest.mark.parametrize(
        "action,stop,target,expected",
        [
            (SignalAction.BUY, 98.0, 102.0, True),
            (SignalAction.BUY, 98.0, 99.0, False),   # target below entry
            (SignalAction.BUY, 101.0, 102.0, False),  # stop above entry
            (SignalAction.SELL, 102.0, 98.0, True),
            (SignalAction.SELL, 102.0, 103.0, False),  # target above entry
            (SignalAction.SELL, 97.0, 98.0, False),   # stop below entry
            (SignalAction.HOLD, 98.0, 102.0, False),
        ],
    )
    def test_ordering(self, action, stop, target, expected):
        assert (
            Strategy.levels_are_ordered(action, 100.0, stop, target) is expected
        )

    def test_placing_both_levels_the_wrong_way_is_caught(self, strategy):
        """A long built with a short's geometry must be rejected."""
        stop = strategy.build_stop_loss(100.0, SignalAction.SELL, None, fallback_pct=2.0)
        target = strategy.build_take_profit(100.0, stop, 2.0, SignalAction.SELL)
        assert not Strategy.levels_are_ordered(
            SignalAction.BUY, 100.0, stop, target
        )