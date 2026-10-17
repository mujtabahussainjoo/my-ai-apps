"""Unit tests for the hard risk engine.

These tests encode the safety contract, not just the happy path. Most of them
assert a *rejection*, because the value of a guardrail is entirely in the cases
where it refuses to act. A regression that turns a rejection into an approval
must fail loudly here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from src.core.config import Settings
from src.core.enums import OrderSide, OrderType, RiskRule, StrategyStatus, TradingMode
from src.core.security import kill_switch
from src.risk.risk_engine import RiskEngine
from src.risk.risk_limits import LimitBreakers
from src.schemas.market import Ticker
from src.schemas.order import OrderRequest
from src.schemas.portfolio import PortfolioSnapshot, Position

EQUITY = 10_000.0
ENTRY = 65_000.0
STOP = 63_700.0
TARGET = 67_600.0


def assess(engine, request, portfolio, **kwargs):
    """Assess with qualification granted explicitly.

    ``RiskEngine.assess`` defaults ``strategy_status`` to CANDIDATE so that a
    caller who forgets it fails closed. Tests about other rules must therefore
    state that qualification holds rather than inherit it.
    """
    kwargs.setdefault("strategy_status", StrategyStatus.QUALIFIED)
    return engine.assess(request, portfolio, **kwargs)


@pytest.fixture(autouse=True)
def clear_global_breakers():
    """The kill switch is process-wide by design, so tests must clear it."""
    kill_switch.release(operator="test-setup")
    yield
    kill_switch.release(operator="test-teardown")


@pytest.fixture
def settings() -> Settings:
    return Settings(trading_mode="paper", market_data_allow_synthetic=True)


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture
def portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity_usd=EQUITY,
        cash_usd=EQUITY,
        peak_equity_usd=EQUITY,
        starting_equity_usd=EQUITY,
        mode=TradingMode.PAPER,
    )


@pytest.fixture
def ticker(now: datetime) -> Ticker:
    return Ticker(
        symbol="BTC/USDT",
        last=ENTRY,
        bid=ENTRY - 5,
        ask=ENTRY + 5,
        timestamp=now,
    )


@pytest.fixture
def engine(settings: Settings):
    """A fresh engine per test: breaker state must not leak between cases."""
    return RiskEngine(settings, LimitBreakers())


def limit_order(**overrides) -> OrderRequest:
    payload = {
        "symbol": "BTC/USDT",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "notional_usd": 400.0,
        "limit_price": ENTRY,
        "stop_loss": STOP,
        "take_profit": TARGET,
        "strategy": "breakout",
        "mode": TradingMode.PAPER,
    }
    payload.update(overrides)
    return OrderRequest(**payload)


def exit_order(**overrides) -> OrderRequest:
    """A risk-reducing market sell. No limit price, and the stop that the entry
    needed is deliberately absent - a stop is an entry-side control."""
    payload = {
        "symbol": "BTC/USDT",
        "side": OrderSide.SELL,
        "order_type": OrderType.MARKET,
        "quantity": 2.0,
        "strategy": None,
        "mode": TradingMode.PAPER,
    }
    payload.update(overrides)
    return OrderRequest(**payload)


def assert_rejected(assessment, rule: str) -> None:
    assert not assessment.allowed, f"expected rejection, got {assessment.verdict.value}"
    assert rule in assessment.failed_rules, (
        f"expected rule {rule!r} to fail; failed {assessment.failed_rules}"
    )
    assert assessment.reasons, "a rejection must explain itself"
    assert assessment.approved_quantity == 0.0
    assert assessment.approved_notional_usd == 0.0


# ── The only path that should ever succeed ────────────────────────────────
class TestApproval:
    def test_well_formed_trade_is_approved(self, engine, portfolio, ticker):
        a = assess(engine, limit_order(), portfolio, ticker=ticker)

        assert a.verdict.value == "approved"
        assert a.approved_notional_usd == pytest.approx(400.0)
        assert a.approved_risk_usd == pytest.approx(400.0 * (ENTRY - STOP) / ENTRY)
        assert a.approved_quantity == pytest.approx(400.0 / ENTRY, rel=1e-6)
        assert not a.requires_approval, "paper trades need no human sign-off"

    def test_short_with_stop_above_entry_is_approved(self, engine, portfolio, ticker):
        a = assess(
            engine,
            limit_order(
                side=OrderSide.SELL,
                stop_loss=ENTRY * 1.02,
                take_profit=ENTRY * 0.92,
            ),
            portfolio,
            ticker=ticker,
        )
        assert a.verdict.value == "approved"

    def test_short_target_above_entry_is_rejected(self, engine, portfolio, ticker):
        """A target on the losing side is a guaranteed loss, not a low reward."""
        a = assess(
            engine,
            limit_order(
                side=OrderSide.SELL,
                stop_loss=ENTRY * 1.02,
                take_profit=ENTRY * 1.10,
            ),
            portfolio,
            ticker=ticker,
        )
        assert_rejected(a, "poor_risk_reward")
        assert "wrong side" in " ".join(a.reasons)

    def test_long_target_below_entry_is_rejected(self, engine, portfolio, ticker):
        assert_rejected(
            assess(
                engine,
                limit_order(stop_loss=ENTRY * 0.98, take_profit=ENTRY * 0.99),
                portfolio,
                ticker=ticker,
            ),
            "poor_risk_reward",
        )

    def test_live_mode_requires_human_approval(self, settings, portfolio, ticker):
        live = Settings(
            trading_mode="live",
            live_trading_enabled=True,
            live_trading_i_understand_the_risk=True,
            market_data_allow_synthetic=False,
        )
        a = assess(
            RiskEngine(live, LimitBreakers()), limit_order(mode=TradingMode.LIVE), portfolio, ticker=ticker
        )
        assert a.verdict.value == "approved"
        assert a.requires_approval, "live orders must be approved by a human"


# ── Stop-loss invariants ──────────────────────────────────────────────────
class TestStopLoss:
    def test_missing_stop_is_rejected(self, engine, portfolio, ticker):
        assert_rejected(
            assess(engine, limit_order(stop_loss=None), portfolio, ticker=ticker), "missing_stop_loss"
        )

    def test_buy_stop_at_or_above_entry_is_rejected(self, engine, portfolio, ticker):
        assert_rejected(
            assess(
                engine,
                limit_order(stop_loss=ENTRY, take_profit=ENTRY * 1.1),
                portfolio,
                ticker=ticker,
            ),
            "stop_distance_out_of_range",
        )

    def test_sell_stop_below_entry_is_rejected(self, engine, portfolio, ticker):
        assert_rejected(
            assess(
                engine,
                limit_order(side=OrderSide.SELL, stop_loss=STOP, take_profit=ENTRY * 0.9),
                portfolio,
                ticker=ticker,
            ),
            "stop_distance_out_of_range",
        )

    def test_stop_beyond_max_distance_is_rejected(self, engine, portfolio, ticker, settings):
        too_wide = ENTRY * (1 - settings.risk_max_stop_distance_pct / 100 * 2)
        assert_rejected(
            assess(
                engine,
                limit_order(stop_loss=too_wide, take_profit=ENTRY * 1.2),
                portfolio,
                ticker=ticker,
            ),
            "stop_distance_out_of_range",
        )

    def test_stop_inside_spread_noise_is_rejected(self, engine, portfolio, ticker, settings):
        too_tight = ENTRY * (1 - settings.risk_min_stop_distance_pct / 200)
        assert_rejected(
            assess(
                engine,
                limit_order(stop_loss=too_tight, take_profit=ENTRY * 1.1),
                portfolio,
                ticker=ticker,
            ),
            "stop_distance_out_of_range",
        )

    def test_engine_derives_a_stop_when_atr_is_available(self, engine, portfolio, ticker, settings):
        a = assess(
            engine,
            limit_order(stop_loss=None, take_profit=ENTRY * 1.12),
            portfolio,
            ticker=ticker,
            atr=900.0,
        )
        assert a.verdict.value == "approved"
        assert a.adjusted_stop_loss is not None
        assert a.adjusted_stop_loss < ENTRY
        distance_pct = (ENTRY - a.adjusted_stop_loss) / ENTRY * 100
        assert settings.risk_min_stop_distance_pct <= distance_pct <= settings.risk_max_stop_distance_pct

    def test_a_derived_stop_still_has_to_satisfy_risk_reward(self, engine, portfolio, ticker):
        """Deriving a stop must not become a way around the R:R gate."""
        a = assess(
            engine,
            limit_order(stop_loss=None, take_profit=ENTRY * 1.05),
            portfolio,
            ticker=ticker,
            atr=900.0,
        )
        assert_rejected(a, "poor_risk_reward")


class TestRiskReward:
    def test_low_reward_to_risk_is_rejected(self, engine, portfolio, ticker):
        assert_rejected(
            assess(
                engine,
                limit_order(stop_loss=ENTRY * 0.98, take_profit=ENTRY * 1.005),
                portfolio,
                ticker=ticker,
            ),
            "poor_risk_reward",
        )

    def test_no_target_is_acceptable(self, engine, portfolio, ticker):
        a = assess(engine, limit_order(take_profit=None), portfolio, ticker=ticker)
        assert a.verdict.value == "approved", "a stop alone is enough protection"


# ── Mode escalation ───────────────────────────────────────────────────────
class TestTradingMode:
    def test_live_is_rejected_while_live_trading_is_disabled(self, engine, portfolio, ticker):
        assert_rejected(
            assess(engine, limit_order(mode=TradingMode.LIVE), portfolio, ticker=ticker),
            "mode_not_allowed",
        )

    def test_cannot_escalate_above_the_configured_mode(self, engine, portfolio, ticker):
        assert_rejected(
            assess(engine, limit_order(mode=TradingMode.TESTNET), portfolio, ticker=ticker),
            "mode_not_allowed",
        )

    def test_a_weaker_mode_is_allowed(self, engine, portfolio, ticker):
        a = assess(engine, limit_order(mode=TradingMode.BACKTEST), portfolio, ticker=ticker)
        assert a.verdict.value == "approved"


# ── Data integrity ────────────────────────────────────────────────────────
class TestMarketData:
    def test_stale_quote_is_rejected(self, engine, portfolio, now):
        stale = Ticker(
            symbol="BTC/USDT",
            last=ENTRY,
            timestamp=now - timedelta(seconds=500),
        )
        assert_rejected(assess(engine, limit_order(), portfolio, ticker=stale), "stale_market_data")

    def test_missing_quote_fails_closed(self, engine, portfolio):
        assert_rejected(assess(engine, limit_order(), portfolio, ticker=None), "stale_market_data")

    def test_market_order_is_priced_at_the_ask(self, engine, portfolio, ticker):
        order = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            notional_usd=400.0,
            stop_loss=ENTRY * 0.98,
            take_profit=ENTRY * 1.08,
            strategy="breakout",
        )
        a = assess(engine, order, portfolio, ticker=ticker)

        assert a.verdict.value == "approved"
        assert a.approved_quantity == pytest.approx(400.0 / ticker.ask, rel=1e-6)
        assert order.limit_price is None, "the caller's request must not be mutated"


# ── Authorisation boundaries ──────────────────────────────────────────────
class TestStrategyAndAgentGates:
    @pytest.mark.parametrize(
        "status",
        [
            StrategyStatus.CANDIDATE,
            StrategyStatus.BACKTESTING,
            StrategyStatus.REJECTED,
            StrategyStatus.RETIRED,
        ],
    )
    def test_unqualified_strategy_is_rejected(self, engine, portfolio, ticker, status):
        assert_rejected(
            assess(engine, limit_order(), portfolio, ticker=ticker, strategy_status=status),
            "strategy_not_qualified",
        )

    def test_missing_strategy_is_rejected(self, engine, portfolio, ticker):
        assert_rejected(
            assess(engine, limit_order(strategy=None), portfolio, ticker=ticker),
            "strategy_not_qualified",
        )

    def test_agent_veto_is_honoured(self, engine, portfolio, ticker):
        assert_rejected(
            assess(engine, limit_order(), portfolio, ticker=ticker, agent_approved=False),
            "agent_not_approved",
        )


# ── Sizing and exposure ───────────────────────────────────────────────────
class TestSizing:
    def test_oversized_request_is_reduced_not_refused(self, engine, portfolio, ticker, settings):
        a = assess(
            engine,
            limit_order(notional_usd=2_000.0, stop_loss=ENTRY * 0.995, take_profit=ENTRY * 1.03),
            portfolio,
            ticker=ticker,
        )
        cap = EQUITY * settings.risk_max_position_pct / 100

        assert a.verdict.value == "approved_reduced"
        assert a.approved_notional_usd == pytest.approx(cap)

    def test_existing_book_forces_a_reduction(self, engine, portfolio, ticker):
        book = [
            Position(
                symbol="BTC/USDT",
                quantity=0.02,
                entry_price=ENTRY,
                current_price=ENTRY,
                stop_loss=ENTRY * 0.98,
            ),
            Position(
                symbol="ETH/USDT", quantity=0.2, entry_price=3_200, current_price=3_200, stop_loss=3_100
            ),
        ]
        a = assess(
            engine,
            limit_order(notional_usd=2_000.0, stop_loss=ENTRY * 0.995, take_profit=ENTRY * 1.03),
            portfolio,
            ticker=ticker,
            positions=book,
        )
        assert a.verdict.value == "approved_reduced"
        assert a.approved_notional_usd < 2_000.0

    def test_book_already_over_the_cap_is_rejected(self, engine, portfolio, ticker):
        book = [Position(symbol="BTC/USDT", quantity=0.8, entry_price=ENTRY, current_price=ENTRY)]
        assert_rejected(
            assess(
                engine,
                limit_order(notional_usd=2_000.0, stop_loss=ENTRY * 0.995, take_profit=ENTRY * 1.03),
                portfolio,
                ticker=ticker,
                positions=book,
            ),
            "max_total_exposure",
        )

    def test_insufficient_cash_is_rejected(self, engine, ticker):
        broke = PortfolioSnapshot(
            equity_usd=EQUITY,
            cash_usd=100.0,
            peak_equity_usd=EQUITY,
            starting_equity_usd=EQUITY,
        )
        assert_rejected(assess(engine, limit_order(), broke, ticker=ticker), "insufficient_balance")

    def test_leverage_above_the_cap_is_rejected(self, engine, portfolio, ticker):
        assert_rejected(
            assess(engine, limit_order(leverage=5.0), portfolio, ticker=ticker),
            "leverage_limit",
        )


# ── Circuit breakers ──────────────────────────────────────────────────────
class TestCircuitBreakers:
    def test_drawdown_limit_halts_trading(self, engine, ticker):
        drawdown = PortfolioSnapshot(
            equity_usd=8_200.0,
            cash_usd=8_200.0,
            peak_equity_usd=EQUITY,
            current_drawdown_pct=18.0,
            starting_equity_usd=EQUITY,
        )
        assert_rejected(assess(engine, limit_order(), drawdown, ticker=ticker), "max_drawdown")
        assert engine.breakers.drawdown_halted

    def test_daily_loss_limit_halts_trading(self, engine, ticker):
        losing = PortfolioSnapshot(
            equity_usd=EQUITY,
            cash_usd=EQUITY,
            peak_equity_usd=EQUITY,
            daily_pnl_usd=-350.0,
            starting_equity_usd=EQUITY,
        )
        assert_rejected(assess(engine, limit_order(), losing, ticker=ticker), "daily_loss_limit")
        assert engine.breakers.daily_loss_halted

    def test_kill_switch_overrides_everything(self, engine, portfolio, ticker):
        engine.engage_kill_switch("operator pressed the button")
        a = assess(engine, limit_order(), portfolio, ticker=ticker)

        assert a.verdict.value == "halted"
        assert not a.approved_notional_usd

    def test_daily_trade_budget_is_enforced(self, settings, portfolio, ticker):
        breakers = LimitBreakers()
        breakers.trades_today = 10
        breakers.trades_today_date = datetime.now(UTC).date()
        a = RiskEngine(settings, breakers).assess(limit_order(), portfolio, ticker=ticker)
        assert_rejected(a, "max_ai_trades_per_day")

    def test_reduction_cannot_rescue_a_fatal_violation(self, engine, portfolio, ticker):
        """The single most important test in this file.

        Shrinking an order must never clear a limit that shrinking cannot fix.
        A live-mode order while live trading is disabled must stay rejected
        even though it also breaches the position cap and could be reduced.
        """
        a = assess(
            engine,
            limit_order(notional_usd=5_000.0, mode=TradingMode.LIVE, strategy=None),
            portfolio,
            ticker=ticker,
            strategy_status=StrategyStatus.REJECTED,
        )

        assert not a.allowed
        for rule in ("mode_not_allowed", "strategy_not_qualified"):
            assert rule in a.failed_rules


# ── Robustness ────────────────────────────────────────────────────────────
def test_an_exception_during_assessment_rejects_rather_than_approves(engine, portfolio, ticker, monkeypatch):
    """Fail closed: a bug in the engine must not become an approval."""
    monkeypatch.setattr(
        engine,
        "_size",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated bug")),
    )
    a = assess(engine, limit_order(), portfolio, ticker=ticker)

    assert not a.allowed
    # The message names the exception type; the detail stays in the log.
    assert "RuntimeError" in " ".join(a.reasons)


class TestExitAssessment:
    """Exits go through the engine too.

    The exemption is narrow on purpose: entry-side admission limits must not
    trap a position behind the cap that created it, but operator halts and mode
    integrity still apply.
    """

    def test_a_stop_is_not_blocked_by_the_exposure_cap(self, settings, now, ticker, portfolio):
        engine = RiskEngine(settings)
        # A book that is far over the exposure cap: entry would be refused.
        crowded = portfolio.model_copy(
            update={
                "positions": [
                    Position(
                        symbol="ETH/USDT",
                        side=OrderSide.BUY,
                        quantity=5.0,
                        entry_price=ENTRY,
                        current_price=ENTRY,
                        mode=TradingMode.PAPER,
                        opened_at=now,
                    )
                ]
            }
        )
        exit_request = exit_order()
        a = assess(engine, exit_request, crowded, ticker=ticker)
        assert a.verdict is not None
        b = engine.assess_exit(exit_request, crowded, ticker=ticker, reason="stop_loss")
        assert b.allowed, b.reasons

    def test_the_exit_approval_carries_the_full_exit_size(self, settings, ticker, portfolio):
        engine = RiskEngine(settings)
        exit_request = exit_order()
        a = engine.assess_exit(exit_request, portfolio, ticker=ticker, reason="take_profit")
        assert a.allowed, a.reasons
        assert a.approved_quantity == pytest.approx(2.0)
        assert a.approved_notional_usd > 0
        assert a.approved_risk_usd == 0.0

    def test_an_unqualified_strategy_does_not_block_an_exit(self, settings, ticker, portfolio):
        """The exit request may carry no strategy at all."""
        engine = RiskEngine(settings)
        a = engine.assess_exit(
            exit_order(),
            portfolio,
            ticker=ticker,
            reason="stop_loss",
        )
        assert a.allowed, a.reasons

    def test_the_kill_switch_still_stops_an_exit(self, settings, ticker, portfolio):
        """An operator halt means 'do not trade', not merely 'do not open risk'."""
        engine = RiskEngine(settings)
        engine.engage_kill_switch("test halt")
        a = engine.assess_exit(
            exit_order(),
            portfolio,
            ticker=ticker,
            reason="stop_loss",
        )
        assert not a.allowed
        assert RiskRule.KILL_SWITCH in a.failed_rules

    def test_a_mode_mismatch_still_stops_an_exit(self, settings, ticker, portfolio):
        engine = RiskEngine(settings)
        a = engine.assess_exit(
            exit_order(mode=TradingMode.LIVE),
            portfolio,
            ticker=ticker,
            reason="stop_loss",
        )
        assert not a.allowed
        assert RiskRule.MODE_NOT_ALLOWED in a.failed_rules

    def test_a_stale_quote_still_stops_an_exit(self, settings, now, portfolio):
        """The exit is priced off the ticker, so a stale one must not be used."""
        engine = RiskEngine(settings)
        stale = Ticker(
            symbol="BTC/USDT",
            last=ENTRY,
            bid=ENTRY - 5,
            ask=ENTRY + 5,
            timestamp=now - timedelta(hours=2),
        )
        a = engine.assess_exit(
            exit_order(),
            portfolio,
            ticker=stale,
            reason="stop_loss",
        )
        assert not a.allowed
        assert RiskRule.STALE_MARKET_DATA in a.failed_rules

    def test_the_exit_is_recorded_in_the_audit_trail(self, settings, ticker, portfolio):
        """An exit that skipped the gate would be invisible after the fact."""
        engine = RiskEngine(settings)
        a = engine.assess_exit(
            exit_order(),
            portfolio,
            ticker=ticker,
            reason="stop_loss",
        )
        assert RiskRule.POSITION_REDUCING in {c.rule for c in a.checks}
