"""Signal processing: turning a third party's message into a trade, safely.

The cases that matter here are the ones where the processor must decline. A
webhook is the only place in the system where a suggestion arrives from outside
the codebase, so it is the only place where "trust the numbers" would be
tempting. Each test below pins one way that temptation is refused.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import src.database.models  # noqa: F401 - registers the mappers
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from src.core.enums import OrderSide, StrategyStatus, TradingMode
from src.database.base import Base
from src.database.repositories import (
    PortfolioRepository,
    SignalRepository,
    StrategyStatusRepository,
)
from src.database.seed import ensure_reference_data
from src.risk.risk_engine import RiskEngine
from src.schemas.base import utcnow
from src.schemas.order import OrderRequest
from src.schemas.signal import Signal, SignalAction, Timeframe
from src.trading.executor import build_paper_executor
from src.trading.signal_processor import MarketQuote, SignalProcessor

ENTRY = 60_000.0
ATR = 600.0  # 1% of entry


class StubQuotes:
    """A quote source with no network and no collector lifecycle."""

    def __init__(self, price: float = ENTRY, atr: float | None = ATR) -> None:
        self.price = price
        self.atr = atr
        self.calls: list[str] = []
        self.fail = False

    def quote(self, symbol: str, timeframe: Timeframe | None = None) -> MarketQuote | None:
        self.calls.append(symbol)
        if self.fail:
            raise RuntimeError("feed unreachable")
        return MarketQuote(symbol=symbol, price=self.price, atr=self.atr, timestamp=utcnow())


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("MARKET_DATA_ALLOW_SYNTHETIC", "true")
    from src.core.config import get_settings

    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def seeded(session: Session) -> StrategyStatusRepository:
    ensure_reference_data(session)
    session.commit()
    return StrategyStatusRepository(session)


@pytest.fixture
def quotes() -> StubQuotes:
    return StubQuotes()


@pytest.fixture
def processor(session: Session, settings, quotes) -> SignalProcessor:
    return SignalProcessor(
        executor=build_paper_executor(session, settings),
        risk=RiskEngine(settings),
        portfolio=PortfolioRepository(session),
        signals=SignalRepository(session),
        strategies=StrategyStatusRepository(session),
        quotes=quotes,
        settings=settings,
        mode=TradingMode.PAPER,
    )


def make_signal(
    session: Session,
    *,
    strategy: str = "breakout",
    action: SignalAction = SignalAction.BUY,
    entry: float = ENTRY,
    stop_loss: float | None = ENTRY - 1_200.0,
    take_profit: float | None = ENTRY + 2_400.0,
    confidence: float = 0.7,
    atr: float | None = ATR,
    created_at=None,
) -> Signal:
    """Record a signal so there is a real row to settle."""
    repo = SignalRepository(session)
    signal = Signal(
        symbol="BTC/USDT",
        timeframe=Timeframe.H1,
        strategy=strategy,
        action=action,
        confidence=confidence,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        atr=atr,
        created_at=created_at or utcnow(),
    )
    signal.id = repo.record(signal)
    session.commit()
    return signal


def status_of(session: Session, signal: Signal) -> tuple[str, str | None, str | None]:
    row = session.get(__import__("src.database.models.trading", fromlist=["Signal"]).Signal, signal.id)
    session.refresh(row)
    return row.status, row.order_id, row.reject_reason


def orders_for(session: Session, signal: Signal) -> list:
    from src.database.models.trading import Order

    return list(session.query(Order).filter(Order.signal_id == signal.id))


# ── the happy path, to prove the refusals below are not vacuous ─────────────


class TestAcceptedSignal:
    def test_a_qualified_strategy_with_a_sane_stop_trades(self, session, seeded, processor, quotes):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session)
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "executed"
        assert status_of(session, signal)[0] == "executed"
        assert len(orders_for(session, signal)) == 1

    def test_the_order_links_back_to_the_signal(self, session, seeded, processor, quotes):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session)
        processor.handle(signal)
        session.commit()

        assert status_of(session, signal)[1] == orders_for(session, signal)[0].id

    def test_processing_a_queue_exhausts_it(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()
        for _ in range(3):
            make_signal(session)

        result = processor.process_pending()
        session.commit()

        assert result.processed == 3
        assert result.executed == 3
        assert result.deferred == 0
        # Nothing left behind to re-trade on the next pass.
        assert processor.process_pending().processed == 0


# ── refusals ────────────────────────────────────────────────────────────────


class TestRefusals:
    def test_an_unqualified_strategy_is_rejected_not_traded(self, session, seeded, processor):
        """The core refusal: a strategy nobody promoted cannot trade."""
        seeded.set("breakout", StrategyStatus.CANDIDATE, qualified=False)
        session.commit()

        signal = make_signal(session)
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "rejected"
        assert orders_for(session, signal) == []

    def test_a_rejection_is_recorded_with_a_reason(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.CANDIDATE, qualified=False)
        session.commit()

        signal = make_signal(session)
        processor.handle(signal)
        session.commit()

        _, order_id, reason = status_of(session, signal)
        assert order_id is None
        assert reason  # the audit trail says why, even with no order

    def test_an_unknown_strategy_is_rejected_without_an_evaluator(self, session, seeded, processor):
        """In isolation there is nothing to re-check the market with."""
        assert processor.evaluate_symbol is None
        signal = make_signal(session, strategy="moon_phase")
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "rejected"
        assert "not a registered strategy" in decision.reason

    def test_a_hold_is_ignored(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session, action=SignalAction.HOLD)
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "ignored"
        assert orders_for(session, signal) == []

    def test_a_stale_signal_is_ignored(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session, created_at=utcnow() - timedelta(days=2))
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "ignored"
        assert "older than" in decision.reason

    def test_an_unreachable_feed_defers_rather_than_trading_a_guess(self, session, seeded, processor, quotes):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()
        quotes.fail = True

        signal = make_signal(session)
        decision = processor.handle(signal)
        session.commit()

        # Deferred, not rejected: the feed may recover, and the age bound stops
        # it queueing forever.
        assert decision.status == "deferred"
        assert status_of(session, signal)[0] == "pending"
        assert orders_for(session, signal) == []

    def test_a_non_positive_entry_cannot_be_constructed(self, session, seeded):
        """The schema refuses it at the boundary, so no such signal exists."""
        with pytest.raises(ValidationError):
            Signal(
                symbol="BTC/USDT",
                timeframe=Timeframe.H1,
                strategy="breakout",
                action=SignalAction.BUY,
                confidence=0.7,
                entry=0.0,
            )

    def test_a_corrupt_row_never_reaches_the_processor(self, session, seeded, processor):
        """The schema is the boundary: a zero-entry row cannot be loaded at all."""
        from src.database.base import new_id
        from src.database.models.trading import Signal as SignalRow

        row = SignalRow(
            id=new_id(),
            symbol="BTC/USDT",
            timeframe="1h",
            strategy="breakout",
            action="buy",
            confidence=0.7,
            entry=0.0,
            created_at=utcnow(),
        )
        session.add(row)
        session.commit()

        with pytest.raises(ValidationError):
            processor.signals.to_schema(row)


# ── triggers: an alert asks, it does not instruct ───────────────────────────


class TestTriggers:
    """A TradingView alert names a symbol, not a trade.

    These tests pin the boundary: the alert's own numbers are never traded, and
    any order comes from a strategy that was asked independently.
    """

    @pytest.fixture
    def evaluated(self):
        calls: list[str] = []
        return calls

    @pytest.fixture
    def processor_with_evaluator(self, processor, evaluated):
        processor.evaluate_symbol = lambda symbol: (
            evaluated.append(symbol) or {"signals": 2, "orders_sent": 1}
        )
        return processor

    def test_a_trigger_consults_the_strategies(self, session, seeded, processor_with_evaluator, evaluated):
        signal = make_signal(session, strategy="tradingview")
        decision = processor_with_evaluator.handle(signal)
        session.commit()

        assert evaluated == ["BTC/USDT"]
        assert decision.status == "ignored"

    def test_a_trigger_does_not_trade_the_alerts_own_numbers(self, session, seeded, processor_with_evaluator):
        """No order carries this signal: the strategies decide, not the sender."""
        signal = make_signal(session, strategy="tradingview")
        processor_with_evaluator.handle(signal)
        session.commit()

        assert orders_for(session, signal) == []
        assert status_of(session, signal)[0] == "ignored"

    def test_a_trigger_is_not_marked_executed(self, session, seeded, processor_with_evaluator):
        """Marking it executed would imply the alert's numbers were traded."""
        signal = make_signal(session, strategy="tradingview")
        decision = processor_with_evaluator.handle(signal)
        session.commit()

        assert decision.status == "ignored"
        _, order_id, _ = status_of(session, signal)
        assert order_id is None

    def test_the_trigger_note_reports_what_the_strategies_concluded(
        self, session, seeded, processor_with_evaluator
    ):
        signal = make_signal(session, strategy="tradingview")
        processor_with_evaluator.handle(signal)
        session.commit()

        reason = status_of(session, signal)[2]
        assert "qualified strategies reviewed BTC/USDT" in reason
        assert "produced 2 signal(s)" in reason
        assert "1 order(s) sent" in reason

    def test_a_failing_evaluator_defers_rather_than_dropping(self, session, seeded, processor):
        def boom(symbol: str):
            raise RuntimeError("no candles for this symbol")

        processor.evaluate_symbol = boom
        signal = make_signal(session, strategy="tradingview")
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "deferred"
        assert status_of(session, signal)[0] == "pending"

    def test_a_named_strategy_still_uses_its_own_path(
        self, session, seeded, processor_with_evaluator, evaluated
    ):
        """An alert naming a real strategy is judged on its own merits."""
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session, strategy="breakout")
        decision = processor_with_evaluator.handle(signal)
        session.commit()

        assert evaluated == []
        assert decision.status == "executed"

    def test_a_trigger_is_still_bounded_by_age(self, session, seeded, processor_with_evaluator, evaluated):
        """A stale alert is not worth re-checking a market for."""
        signal = make_signal(session, strategy="tradingview", created_at=utcnow() - timedelta(days=3))
        decision = processor_with_evaluator.handle(signal)
        session.commit()

        assert decision.status == "ignored"
        assert evaluated == []


# ── untrusted protective levels ─────────────────────────────────────────────


class TestUntrustedLevels:
    """A sender-supplied stop drives position size, so it cannot be obeyed blindly."""

    def test_an_absurdly_tight_stop_is_widened(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        # 0.1% stop: obeyed literally it would ask for ~100x the size.
        signal = make_signal(session, stop_loss=ENTRY - 60.0)
        decision = processor.handle(signal)
        session.commit()

        assert "closer than" in decision.reason
        order = orders_for(session, signal)[0]
        # Sized off the widened stop, not the sender's.
        assert order.quantity < 1.0

    def test_a_stop_above_entry_is_replaced(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session, stop_loss=ENTRY + 500.0)
        decision = processor.handle(signal)
        session.commit()

        assert "not below entry" in decision.reason
        assert orders_for(session, signal)[0].stop_loss < ENTRY

    def test_a_missing_stop_is_filled_from_atr(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session, stop_loss=None)
        decision = processor.handle(signal)
        session.commit()

        assert "stop absent" in decision.reason
        assert orders_for(session, signal)[0].stop_loss == pytest.approx(ENTRY - 2 * ATR)

    def test_a_wider_stop_than_atr_is_honoured(self, session, seeded, processor):
        """Caution is the sender's prerogative; only tightening is overridden."""
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        # 2.5% stop: wider than the 2xATR default of 2% but inside the 5% policy
        # ceiling, with a target clearing the required 2:1 reward-to-risk.
        signal = make_signal(session, stop_loss=ENTRY - 1_500.0, take_profit=ENTRY + 3_600.0)
        processor.handle(signal)
        session.commit()

        order = orders_for(session, signal)[0]
        assert order.stop_loss == pytest.approx(ENTRY - 1_500.0)
        # A wider stop means a smaller position, not a bigger one.
        assert order.quantity < 0.07

    def test_a_widened_stop_that_breaks_risk_reward_is_refused(self, session, seeded, processor):
        """Widening a stop can turn a good idea into a bad trade; that is caught."""
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        # A 4% stop inside the policy ceiling, but a target only half as far,
        # so the trade never clears 1:1 before the engine is even consulted.
        signal = make_signal(session, stop_loss=ENTRY - 2_400.0, take_profit=ENTRY + 1_200.0)
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "rejected"
        assert "risk/reward" in decision.reason
        assert "below the 1.0 minimum" in decision.reason
        assert orders_for(session, signal) == []

    def test_a_missing_take_profit_is_refused(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session, take_profit=None)
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "rejected"
        assert "take-profit" in decision.reason

    def test_a_stale_alert_price_is_reported(self, session, seeded, processor, quotes):
        """The alert described a market that has already moved."""
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()
        quotes.price = ENTRY * 0.98  # live price fell 2% since the alert

        signal = make_signal(session, entry=ENTRY, stop_loss=ENTRY - 1_200.0, take_profit=ENTRY + 3_600.0)
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "executed"
        assert "live is" in decision.reason

    def test_the_stop_is_anchored_to_the_live_price_not_the_alert(self, session, seeded, processor, quotes):
        """Regression: anchoring to the alert's price put the stop inside noise.

        Sizing and the stop must both be measured from the price the market
        order will actually fill at, or a modestly stale alert produces a stop
        the risk engine rightly refuses.
        """
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()
        quotes.price = ENTRY * 0.98

        signal = make_signal(session, entry=ENTRY, stop_loss=ENTRY - 1_200.0, take_profit=ENTRY + 3_600.0)
        processor.handle(signal)
        session.commit()

        order = orders_for(session, signal)[0]
        live = ENTRY * 0.98
        # Two ATR below the live price, not the alert's price. This is the
        # assertion that discriminates: anchored to the alert, the stop would
        # have been 1200 below 60000 instead.
        assert float(order.stop_loss) == pytest.approx(live - 2 * ATR, rel=1e-6)
        # Whatever size the engine settled on, the risk it carries is measured
        # from the live price and stays inside the 1% budget.
        risked = float(order.quantity) * abs(live - float(order.stop_loss))
        assert 0 < risked <= 100.0

    def test_without_atr_a_stop_cannot_be_set_so_nothing_trades(self, session, seeded, processor, quotes):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()
        quotes.atr = 0.0

        signal = make_signal(session, atr=None)
        decision = processor.handle(signal)
        session.commit()

        assert decision.status == "rejected"
        assert "no ATR" in decision.reason
        assert orders_for(session, signal) == []


# ── no bypass, no double-trade ──────────────────────────────────────────────


class TestContainment:
    def test_the_risk_engine_sees_every_signal(self, session, seeded, processor, monkeypatch):
        """Proof the processor has no shortcut around assessment."""
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        seen: list[OrderRequest] = []
        original = processor.risk.assess

        def spy(request, portfolio, **kwargs):
            seen.append(request)
            return original(request, portfolio, **kwargs)

        monkeypatch.setattr(processor.risk, "assess", spy)

        signal = make_signal(session, stop_loss=ENTRY - 60.0)
        processor.handle(signal)

        assert len(seen) == 1

    def test_the_executor_is_only_called_after_approval(self, session, seeded, processor, monkeypatch):
        seeded.set("breakout", StrategyStatus.CANDIDATE, qualified=False)
        session.commit()

        calls: list = []
        monkeypatch.setattr(processor.executor, "execute", lambda *a, **k: calls.append(a))

        processor.handle(make_signal(session))

        assert calls == []

    def test_a_settled_signal_is_not_reprocessed(self, session, seeded, processor):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session)
        processor.handle(signal)
        session.commit()

        # Ask directly: the row is no longer pending, so a second pass skips it.
        assert SignalRepository(session).pending() == []

    def test_an_unrecorded_signal_is_refused(self, session, seeded, processor):
        with pytest.raises(ValueError, match="not been recorded"):
            processor.handle(
                Signal(
                    symbol="BTC/USDT",
                    timeframe=Timeframe.H1,
                    strategy="breakout",
                    action=SignalAction.BUY,
                    confidence=0.7,
                    entry=ENTRY,
                    stop_loss=ENTRY - 1_200.0,
                )
            )

    def test_a_sell_closes_without_entry_only_checks(self, session, seeded, processor, quotes):
        """A sell for a symbol with no position is still an order to the risk engine."""
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        session.commit()

        signal = make_signal(session, action=SignalAction.SELL, stop_loss=None)
        decision = processor.handle(signal)
        session.commit()

        # The decision comes from the risk engine, whatever it was.
        assert decision.status in {"executed", "rejected"}
        if decision.status == "executed":
            assert orders_for(session, signal)[0].side == OrderSide.SELL
