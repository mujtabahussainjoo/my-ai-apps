"""Accounting and causality invariants for the backtest engine.

If these break, every strategy metric and every qualification decision built on
top of them is wrong in a way that looks plausible on a dashboard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from src.backtesting.engine import BacktestConfig, BacktestEngine, _pivot_at
from src.core.constants import PIVOT_RIGHT
from src.core.enums import Timeframe
from src.schemas.market import Candle

START = datetime(2024, 1, 1, tzinfo=UTC)


def make_candles(n: int = 1500, seed: int = 7) -> list[Candle]:
    """Geometric random walk with mild drift: no real trend structure."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, n)) + 0.0009 * t)
    out: list[Candle] = []
    for i, c in enumerate(close):
        o = float(close[i - 1]) if i else float(c)
        out.append(
            Candle(
                symbol="BTC/USDT",
                timestamp=START + timedelta(hours=i),
                open=o,
                high=max(o, float(c)) * 1.004,
                low=min(o, float(c)) * 0.996,
                close=float(c),
                volume=float(abs(rng.normal(800, 200))),
            )
        )
    return out


@pytest.fixture(scope="module")
def candles() -> list[Candle]:
    return make_candles()


@pytest.fixture(scope="module")
def breakout_run(candles):
    return BacktestEngine().run(
        candles, BacktestConfig(strategy="breakout", symbol="BTC/USDT", timeframe=Timeframe.H1)
    )


class TestFeeAccounting:
    def test_trade_pnl_is_net_of_both_legs_of_fees(self, breakout_run):
        for trade in breakout_run.trades:
            assert trade.pnl_usd == pytest.approx(trade.gross_pnl_usd - trade.fees_usd), (
                f"{trade.id}: pnl {trade.pnl_usd} != gross {trade.gross_pnl_usd} minus fees {trade.fees_usd}"
            )

    def test_fees_are_never_zero(self, breakout_run):
        assert all(t.fees_usd > 0 for t in breakout_run.trades)

    def test_metrics_agree_with_the_sum_of_trades(self, breakout_run):
        total = sum(t.pnl_usd for t in breakout_run.trades)
        assert breakout_run.metrics.net_profit_usd == pytest.approx(total)

    def test_equity_curve_agrees_with_trade_pnl(self, breakout_run):
        """Cash, metrics and the curve are three views of one number."""
        expected = breakout_run.config.starting_equity + sum(t.pnl_usd for t in breakout_run.trades)
        assert breakout_run.equity_curve[-1] == pytest.approx(expected)

    def test_total_fees_match_the_sum_of_trades(self, breakout_run):
        assert breakout_run.metrics.total_fees_usd == pytest.approx(
            sum(t.fees_usd for t in breakout_run.trades)
        )


class TestExitGeometry:
    def test_no_trade_exits_beyond_its_target_on_the_winning_side(self, breakout_run):
        for t in breakout_run.trades:
            if t.exit_reason == "take_profit":
                assert t.pnl_usd > 0, (
                    f"{t.id} filled a 'take profit' yet lost money: "
                    f"{t.side.value} {t.entry_price} -> {t.exit_price}"
                )

    def test_no_trade_exits_past_its_stop_on_the_losing_side(self, breakout_run):
        for t in breakout_run.trades:
            if t.exit_reason == "stop_loss":
                assert t.pnl_usd < 0, f"{t.id} filled a 'stop loss' yet made money"

    def test_realised_r_multiple_tracks_the_planned_ratio(self, breakout_run):
        winners = [t for t in breakout_run.trades if t.exit_reason == "take_profit"]
        assert winners, "expected at least one target hit"
        for t in winners:
            assert t.risk_multiple is not None
            assert t.risk_multiple > 0.9, (
                f"{t.id} reached its target but realised only {t.risk_multiple:.2f}R"
            )

    def test_both_sides_are_exercised(self, breakout_run):
        """Regression guard for the inverted short target."""
        sides = {t.side.value for t in breakout_run.trades}
        assert {"buy", "sell"} <= sides


class TestPlausibility:
    """A 2:1 payoff cannot produce these numbers on a random walk."""

    @pytest.mark.parametrize("strategy", ["breakout", "momentum", "ema_rsi_macd", "mean_reversion"])
    def test_strategies_produce_tradeable_statistics(self, candles, strategy):
        result = BacktestEngine().run(
            candles,
            BacktestConfig(strategy=strategy, symbol="BTC/USDT", timeframe=Timeframe.H1),
        )
        m = result.metrics

        assert m.total_trades > 0, f"{strategy} produced no trades"
        assert 0.10 <= m.win_rate <= 0.75, (
            f"{strategy} win rate {m.win_rate:.1%} is implausible for a stop-and-target system"
        )
        assert m.max_drawdown_pct < 90.0, (
            f"{strategy} drawdown {m.max_drawdown_pct:.1f}% suggests inverted exits"
        )
        assert m.profit_factor > 0.05, (
            f"{strategy} profit factor {m.profit_factor:.2f} implies every trade lost"
        )

    def test_results_are_deterministic(self, candles):
        cfg = BacktestConfig(strategy="momentum", symbol="BTC/USDT", timeframe=Timeframe.H1)
        first = BacktestEngine().run(candles, cfg).metrics.net_profit_usd
        second = BacktestEngine().run(candles, cfg).metrics.net_profit_usd
        assert first == second


class TestPivotLag:
    def test_pivot_is_read_only_once_confirmed(self):
        series = np.full(20, np.nan)
        series[5] = 100.0
        # At bar 5+right the pivot is knowable; before that it is not.
        assert _pivot_at(series, 5 + PIVOT_RIGHT, PIVOT_RIGHT) == 100.0
        assert _pivot_at(series, 5, PIVOT_RIGHT) is None
        assert _pivot_at(series, 4, PIVOT_RIGHT) is None

    def test_no_negative_index_access(self):
        series = np.full(20, np.nan)
        series[0] = 100.0
        assert _pivot_at(series, 0, PIVOT_RIGHT) is None
        assert _pivot_at(series, 1, PIVOT_RIGHT) is None

    def test_missing_series_is_tolerated(self):
        assert _pivot_at(None, 50, PIVOT_RIGHT) is None
