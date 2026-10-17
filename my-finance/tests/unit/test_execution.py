"""Execution-layer tests.

The recurring theme: the risk engine's numbers win. Several tests deliberately
try to smuggle a larger order past the gate, because that is the failure mode
that matters.
"""

from __future__ import annotations

import pytest
import src.database.models  # noqa: F401 - registers the mappers
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from src.core.enums import OrderSide, RiskVerdict, Severity, TradingMode
from src.core.exceptions import ExecutionError
from src.core.security import LiveTradingDisabledError
from src.database.base import Base
from src.schemas.market import Ticker
from src.schemas.order import OrderRequest
from src.schemas.risk import RiskAssessment, RiskCheck
from src.trading.base import ExecutionInstruction, fee_for, fill_price_for
from src.trading.executor import (
    ExecutionRejected,
    ExecutorConfig,
    OrderExecutor,
)
from src.trading.live.broker import ExchangeBroker
from src.trading.paper.broker import PaperBroker

FEE_RATE = 0.001
SLIPPAGE = 0.0005


# ── Fixtures ────────────────────────────────────────────────────────────────


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
def ticker() -> Ticker:
    return Ticker(symbol="BTC/USDT", last=100.0, bid=99.5, ask=100.5)


@pytest.fixture
def broker(session: Session) -> PaperBroker:
    return PaperBroker(session, taker_fee_rate=FEE_RATE, slippage_rate=SLIPPAGE, starting_cash=10_000.0)


@pytest.fixture
def executor(session: Session, broker: PaperBroker) -> OrderExecutor:
    return OrderExecutor(session, broker, config=ExecutorConfig(mode=TradingMode.PAPER))


def buy_request(**overrides) -> OrderRequest:
    base = {
        "symbol": "BTC/USDT",
        "side": OrderSide.BUY,
        "order_type": "market",
        "quantity": 1.0,
        "stop_loss": 90.0,
        "take_profit": 120.0,
        "strategy": "breakout",
        "mode": TradingMode.PAPER,
    }
    base.update(overrides)
    return OrderRequest(**base)


def approved(**overrides) -> RiskAssessment:
    base = {
        "verdict": RiskVerdict.APPROVED,
        "approved_quantity": 1.0,
        "approved_notional_usd": 100.0,
    }
    base.update(overrides)
    return RiskAssessment(**base)


# ── Fill pricing ────────────────────────────────────────────────────────────


class TestFillPricing:
    def test_buy_crosses_the_ask_and_sell_hits_the_bid(self):
        """A mid-price fill would flatter paper results."""
        buy = fill_price_for(
            Ticker(symbol="BTC/USDT", last=100.0, bid=99.5, ask=100.5), "buy", slippage_rate=0
        )
        sell = fill_price_for(
            Ticker(symbol="BTC/USDT", last=100.0, bid=99.5, ask=100.5), "sell", slippage_rate=0
        )
        assert buy == 100.5
        assert sell == 99.5
        assert buy > sell

    def test_slippage_moves_the_fill_against_the_trader(self):
        market = Ticker(symbol="BTC/USDT", last=100.0, bid=99.5, ask=100.5)
        buy = fill_price_for(market, "buy", slippage_rate=0.01)
        sell = fill_price_for(market, "sell", slippage_rate=0.01)
        assert buy == pytest.approx(101.505)
        assert sell == pytest.approx(98.505)

    def test_falls_back_to_last_price_without_a_book(self):
        market = Ticker(symbol="BTC/USDT", last=100.0)
        assert fill_price_for(market, "buy", slippage_rate=0) == 100.0

    def test_buy_limit_above_the_market_does_not_fill(self):
        from src.core.enums import OrderType

        market = Ticker(symbol="BTC/USDT", last=100.0, bid=99.5, ask=100.5)
        price = fill_price_for(market, "buy", slippage_rate=0, limit_price=90.0, order_type=OrderType.LIMIT)
        assert price is None

    def test_buy_limit_at_or_below_the_market_fills_at_the_limit(self):
        from src.core.enums import OrderType

        market = Ticker(symbol="BTC/USDT", last=100.0, bid=99.5, ask=100.5)
        price = fill_price_for(market, "buy", slippage_rate=0, limit_price=101.0, order_type=OrderType.LIMIT)
        assert price == 101.0

    def test_sell_limit_below_the_market_does_not_fill(self):
        from src.core.enums import OrderType

        market = Ticker(symbol="BTC/USDT", last=100.0, bid=99.5, ask=100.5)
        price = fill_price_for(market, "sell", slippage_rate=0, limit_price=110.0, order_type=OrderType.LIMIT)
        assert price is None

    def test_market_order_ignores_a_limit_price(self):
        """A market order must never rest, however the caller labels it."""
        from src.core.enums import OrderType

        market = Ticker(symbol="BTC/USDT", last=100.0, bid=99.5, ask=100.5)
        price = fill_price_for(market, "buy", slippage_rate=0, limit_price=50.0, order_type=OrderType.MARKET)
        assert price == 100.5

    def test_fee_is_proportional_to_notional(self):
        assert fee_for(1000.0, 0.001) == pytest.approx(1.0)
        assert fee_for(0.0, 0.001) == 0.0


# ── Paper broker ────────────────────────────────────────────────────────────


class TestPaperBroker:
    def test_market_buy_fills_immediately_with_fee_and_slippage(self, broker: PaperBroker, ticker: Ticker):
        instruction = ExecutionInstruction(request=buy_request(), quantity=1.0, mode=TradingMode.PAPER)
        report = broker.submit(instruction, ticker)
        assert report.is_filled
        assert report.filled_quantity == pytest.approx(1.0)
        expected_price = 100.5 * (1 + SLIPPAGE)
        assert report.average_price == pytest.approx(expected_price)
        assert report.fee_usd == pytest.approx(expected_price * 1.0 * FEE_RATE)

    def test_paper_never_fills_at_mid(self, broker: PaperBroker, ticker: Ticker):
        """Regression guard: mid fills made paper results look better than live."""
        instruction = ExecutionInstruction(request=buy_request(), quantity=1.0, mode=TradingMode.PAPER)
        report = broker.submit(instruction, ticker)
        assert report.average_price != pytest.approx(ticker.mid)

    def test_cash_is_debited_and_asset_credited(self, broker: PaperBroker, ticker: Ticker):
        instruction = ExecutionInstruction(request=buy_request(), quantity=2.0, mode=TradingMode.PAPER)
        report = broker.submit(instruction, ticker)
        cash = broker.fetch_balances()["USDT"]
        expected_cost = report.average_price * 2.0 + report.fee_usd
        assert cash == pytest.approx(10_000.0 - expected_cost)
        assert broker.portfolio.get_balance("BTC", "paper").free == pytest.approx(2.0)

    def test_position_is_opened_with_stop_and_target(self, broker: PaperBroker, ticker: Ticker):
        instruction = ExecutionInstruction(
            request=buy_request(),
            quantity=1.0,
            mode=TradingMode.PAPER,
            stop_loss=90.0,
            take_profit=120.0,
        )
        broker.submit(instruction, ticker)
        position = broker.portfolio.get_position("BTC/USDT", "paper")
        assert position is not None
        assert position.quantity == pytest.approx(1.0)
        assert position.stop_loss == 90.0
        assert position.take_profit == 120.0

    def test_incrementing_adds_at_a_weighted_average_price(self, broker: PaperBroker, ticker: Ticker):
        broker.submit(
            ExecutionInstruction(request=buy_request(), quantity=1.0, mode=TradingMode.PAPER), ticker
        )
        higher = Ticker(symbol="BTC/USDT", last=110.0, bid=109.5, ask=110.5)
        broker.submit(
            ExecutionInstruction(request=buy_request(quantity=3.0), quantity=3.0, mode=TradingMode.PAPER),
            higher,
        )
        position = broker.portfolio.get_position("BTC/USDT", "paper")
        assert position.quantity == pytest.approx(4.0)
        expected = (100.5 * (1 + SLIPPAGE) * 1 + 110.5 * (1 + SLIPPAGE) * 3) / 4
        assert position.entry_price == pytest.approx(expected)

    def test_opposite_side_closes_the_existing_position(self, broker: PaperBroker, ticker: Ticker):
        broker.submit(
            ExecutionInstruction(request=buy_request(), quantity=1.0, mode=TradingMode.PAPER), ticker
        )
        broker.submit(
            ExecutionInstruction(
                request=buy_request(side=OrderSide.SELL), quantity=1.0, mode=TradingMode.PAPER
            ),
            ticker,
        )
        assert broker.portfolio.get_position("BTC/USDT", "paper") is None
        closed = broker.trades.closed_trades("paper")
        assert len(closed) == 1
        assert closed[0].exit_reason == "signal_flip"

    def test_sell_does_not_credit_cash_it_does_not_have(self, broker: PaperBroker, ticker: Ticker):
        """Selling more than held must not invent USD."""
        from src.schemas.base import utcnow
        from src.schemas.portfolio import Position

        broker.portfolio.upsert_position(
            Position(symbol="BTC/USDT", quantity=1.0, entry_price=100.0, opened_at=utcnow())
        )
        instruction = ExecutionInstruction(
            request=buy_request(side=OrderSide.SELL), quantity=5.0, mode=TradingMode.PAPER
        )
        with pytest.raises(ValueError):
            broker.submit(instruction, ticker)
        session_cash = broker.portfolio.get_balance("USDT", "paper").free
        assert session_cash == pytest.approx(10_000.0)

    def test_unfilled_limit_order_rests_open(self, broker: PaperBroker, ticker: Ticker):
        instruction = ExecutionInstruction(
            request=buy_request(order_type="limit", limit_price=50.0),
            quantity=1.0,
            mode=TradingMode.PAPER,
        )
        report = broker.submit(instruction, ticker)
        assert not report.is_filled
        assert report.status == "open"
        assert report.filled_quantity == 0.0

    def test_cancel_removes_a_resting_order(self, broker: PaperBroker, ticker: Ticker):
        instruction = ExecutionInstruction(
            request=buy_request(order_type="limit", limit_price=50.0),
            quantity=1.0,
            mode=TradingMode.PAPER,
        )
        report = broker.submit(instruction, ticker)
        assert broker.cancel(report.client_order_id)
        assert broker.orders.by_client_order_id(report.client_order_id).status == "cancelled"

    def test_cancelling_twice_is_harmless(self, broker: PaperBroker, ticker: Ticker):
        instruction = ExecutionInstruction(
            request=buy_request(order_type="limit", limit_price=50.0),
            quantity=1.0,
            mode=TradingMode.PAPER,
        )
        report = broker.submit(instruction, ticker)
        broker.cancel(report.client_order_id)
        assert broker.cancel(report.client_order_id) is False

    def test_mark_to_market_updates_unrealised_pnl(self, broker: PaperBroker, ticker: Ticker):
        broker.submit(
            ExecutionInstruction(request=buy_request(), quantity=1.0, mode=TradingMode.PAPER), ticker
        )
        broker.mark_to_market({"BTC/USDT": Ticker(symbol="BTC/USDT", last=150.0, bid=149.5, ask=150.5)})
        position = broker.portfolio.get_position("BTC/USDT", "paper")
        assert position.current_price == 150.0
        assert position.unrealized_pnl_usd > 0

    def test_instruction_rejects_a_non_positive_quantity(self):
        with pytest.raises(ExecutionError):
            ExecutionInstruction(request=buy_request(), quantity=0.0, mode=TradingMode.PAPER)


# ── The risk gate ───────────────────────────────────────────────────────────


class TestRiskGate:
    def test_rejected_assessment_never_reaches_the_venue(
        self, executor: OrderExecutor, ticker: Ticker, broker: PaperBroker
    ):
        assessment = RiskAssessment(
            verdict=RiskVerdict.REJECTED,
            checks=[
                RiskCheck(
                    rule="max_position_size",
                    passed=False,
                    message="position 47% > limit 10%",
                    severity=Severity.CRITICAL,
                )
            ],
        )
        with pytest.raises(ExecutionRejected, match="max_position_size"):
            executor.execute(buy_request(quantity=50.0), assessment, ticker=ticker)
        assert broker.orders.recent() == []

    def test_halted_assessment_never_reaches_the_venue(
        self, executor: OrderExecutor, ticker: Ticker, broker: PaperBroker
    ):
        with pytest.raises(ExecutionRejected):
            executor.execute(buy_request(), RiskAssessment(verdict=RiskVerdict.HALTED), ticker=ticker)
        assert broker.orders.recent() == []

    def test_executor_uses_the_reduced_quantity_not_the_request(
        self, executor: OrderExecutor, ticker: Ticker, broker: PaperBroker
    ):
        """The central invariant: risk decides the size, the caller cannot."""
        assessment = approved(verdict=RiskVerdict.APPROVED_REDUCED, approved_quantity=0.25)
        outcome = executor.execute(buy_request(quantity=10.0), assessment, ticker=ticker)
        assert outcome.fill.filled_quantity == pytest.approx(0.25)
        stored = broker.orders.get(outcome.order_id)
        assert stored.quantity == pytest.approx(0.25)

    def test_unsized_approval_is_refused_rather_than_falling_back(
        self, executor: OrderExecutor, ticker: Ticker, broker: PaperBroker
    ):
        """Regression guard for an approved-but-zero assessment.

        Falling back to request.quantity here would return to the caller the
        authority the risk engine just withheld.
        """
        assessment = approved(approved_quantity=0.0, approved_notional_usd=0.0)
        with pytest.raises(ExecutionRejected, match="bypass the risk gate"):
            executor.execute(buy_request(quantity=10.0), assessment, ticker=ticker)
        assert broker.orders.recent() == []

    def test_notional_only_approval_is_converted_using_the_limit_price(
        self, executor: OrderExecutor, ticker: Ticker
    ):
        assessment = approved(approved_quantity=0.0, approved_notional_usd=200.0)
        # The limit must be marketable (above the ask) or it correctly rests.
        outcome = executor.execute(
            buy_request(order_type="limit", limit_price=101.0, quantity=99.0),
            assessment,
            ticker=ticker,
        )
        # Notional authorisation converts at the limit price, not at the ask.
        assert outcome.fill.filled_quantity == pytest.approx(200.0 / 101.0)

    def test_adjusted_stop_wins_over_the_requested_stop(self, executor: OrderExecutor, ticker: Ticker):
        """If the risk engine widened the stop, the widened value must be used."""
        assessment = approved(adjusted_stop_loss=75.0, adjusted_take_profit=150.0)
        outcome = executor.execute(buy_request(stop_loss=99.0, take_profit=101.0), assessment, ticker=ticker)
        stored = executor.orders.get(outcome.order_id)
        assert stored.stop_loss == 75.0
        assert stored.take_profit == 150.0

    def test_mode_mismatch_is_refused(self, executor: OrderExecutor, ticker: Ticker, broker: PaperBroker):
        with pytest.raises(ExecutionRejected, match="does not match executor mode"):
            executor.execute(buy_request(mode=TradingMode.LIVE), approved(), ticker=ticker)
        assert broker.orders.recent() == []

    def test_rejection_is_written_to_the_audit_trail(self, executor: OrderExecutor, ticker: Ticker):
        assessment = RiskAssessment(
            verdict=RiskVerdict.REJECTED,
            checks=[RiskCheck(rule="daily_loss_limit", passed=False, message="loss breach")],
        )
        with pytest.raises(ExecutionRejected):
            executor.execute(buy_request(), assessment, ticker=ticker)
        events = executor.events.recent(limit=10)
        assert any("execution_rejected" in (e.event or "") for e in events)
        assert executor.risk.failed_checks(limit=10)

    def test_successful_execution_records_a_snapshot(self, executor: OrderExecutor, ticker: Ticker):
        executor.execute(buy_request(), approved(), ticker=ticker)
        assert executor.portfolio.latest_snapshot("paper") is not None

    def test_repeated_submission_of_one_key_does_not_double_fill(
        self, executor: OrderExecutor, ticker: Ticker, broker: PaperBroker
    ):
        """Replay protection at the execution boundary."""
        request = buy_request(idempotency_key="fixed-key-1")
        first = executor.execute(request, approved(), ticker=ticker)
        second = executor.execute(request, approved(), ticker=ticker)
        assert second.order_id == first.order_id
        position = broker.portfolio.get_position("BTC/USDT", "paper")
        assert position.quantity == pytest.approx(1.0)


class TestLiveGate:
    def test_exchange_broker_requires_credentials(self):
        with pytest.raises(ExecutionError, match="credentials"):
            ExchangeBroker(TradingMode.TESTNET, api_key="", api_secret="")

    def test_exchange_broker_refuses_paper_mode(self):
        with pytest.raises(ExecutionError, match="cannot run in mode"):
            ExchangeBroker(TradingMode.PAPER, api_key="k", api_secret="s")

    def test_live_from_settings_requires_both_gates(self):
        from src.core.config import Settings

        settings = Settings(trading_mode="live", market_data_allow_synthetic=False)
        with pytest.raises(LiveTradingDisabledError):
            ExchangeBroker.from_settings(settings, client=object())

    def test_live_from_settings_requires_the_acknowledgement_too(self):
        from src.core.config import Settings

        settings = Settings(
            trading_mode="live",
            market_data_allow_synthetic=False,
            live_trading_enabled=True,
            live_trading_i_understand_the_risk=False,
            exchange_api_key="k",
            exchange_api_secret="s",
        )
        with pytest.raises(LiveTradingDisabledError, match="UNDERSTAND_THE_RISK"):
            ExchangeBroker.from_settings(settings, client=object())

    def test_live_submission_revalidates_the_gates_at_send_time(self, session: Session, ticker: Ticker):
        """Gates are checked again on submit, not only at construction."""
        broker = ExchangeBroker(TradingMode.LIVE, api_key="k", api_secret="s", client=object())
        instruction = ExecutionInstruction(
            request=buy_request(mode=TradingMode.LIVE), quantity=1.0, mode=TradingMode.LIVE
        )
        with pytest.raises(LiveTradingDisabledError):
            broker.submit(instruction, ticker)

    def test_live_executor_demands_an_approval_id(self, session: Session, ticker: Ticker):
        broker = ExchangeBroker(TradingMode.LIVE, api_key="k", api_secret="s", client=object())
        broker._live_enabled = True
        broker._live_acknowledged = True
        executor = OrderExecutor(session, broker, config=ExecutorConfig(mode=TradingMode.LIVE))
        assessment = approved(requires_approval=True)
        with pytest.raises(ExecutionRejected, match="human approval"):
            executor.execute(buy_request(mode=TradingMode.LIVE), assessment, ticker=ticker)


# ── Exits ───────────────────────────────────────────────────────────────────


class TestPositionExit:
    def test_close_position_flattens_the_book(
        self, executor: OrderExecutor, broker: PaperBroker, ticker: Ticker
    ):
        executor.execute(
            buy_request(),
            approved(),
            ticker=ticker,
        )
        assert broker.portfolio.get_position("BTC/USDT", "paper") is not None
        executor.close_position("BTC/USDT", 130.0, reason="take_profit", ticker=ticker)
        assert broker.portfolio.get_position("BTC/USDT", "paper") is None

    def test_exit_fills_at_the_market_not_the_requested_price(
        self, executor: OrderExecutor, broker: PaperBroker, ticker: Ticker
    ):
        """A trigger price is a wish; the fill is what the market offers.

        Asking to exit at 130 when the bid is 99.5 must not book a profit that
        the market never gave. This is the gap risk that stops backtests from
        being fantasy.
        """
        executor.execute(buy_request(), approved(), ticker=ticker)
        executor.close_position("BTC/USDT", 130.0, reason="take_profit", ticker=ticker)
        closed = broker.trades.closed_trades("paper")
        assert len(closed) == 1
        expected_fill = 99.5 * (1 - SLIPPAGE)
        assert float(closed[0].exit_price) == pytest.approx(expected_fill)
        assert closed[0].pnl_usd < 0, "exiting at 130 into a 99.5 market is a loss"

    def test_close_position_realises_pnl_on_a_real_gain(
        self, executor: OrderExecutor, broker: PaperBroker, ticker: Ticker
    ):
        executor.execute(buy_request(), approved(), ticker=ticker)
        higher = Ticker(symbol="BTC/USDT", last=130.0, bid=129.5, ask=130.5)
        executor.close_position("BTC/USDT", 130.0, reason="take_profit", ticker=higher)
        closed = broker.trades.closed_trades("paper")
        assert closed[0].pnl_usd > 0
        assert closed[0].exit_reason == "take_profit"

    def test_stop_loss_exit_is_not_recorded_as_a_signal_flip(
        self, executor: OrderExecutor, broker: PaperBroker, ticker: Ticker
    ):
        """Exit reasons drive performance attribution.

        Losing the reason silently files every stop under "signal_flip", which
        makes stop-loss analysis impossible without any error being raised.
        """
        executor.execute(buy_request(), approved(), ticker=ticker)
        crashed = Ticker(symbol="BTC/USDT", last=80.0, bid=79.5, ask=80.5)
        executor.close_position("BTC/USDT", 90.0, reason="stop_loss", ticker=crashed)
        closed = broker.trades.closed_trades("paper")
        assert closed[0].exit_reason == "stop_loss"

    def test_paper_cannot_open_a_short(self, executor: OrderExecutor, broker: PaperBroker, ticker: Ticker):
        """Spot paper trading has no shorting; a reversal must flatten, not flip."""
        executor.execute(buy_request(quantity=1.0), approved(), ticker=ticker)
        executor.close_position("BTC/USDT", 105.0, reason="manual", ticker=ticker)
        assert broker.portfolio.get_position("BTC/USDT", "paper") is None
        assert broker.portfolio.get_balance("BTC", "paper").free == pytest.approx(0.0)

    def test_closing_a_missing_position_is_refused(self, executor: OrderExecutor, ticker: Ticker):
        with pytest.raises(ExecutionRejected, match="no open position"):
            executor.close_position("DOGE/USDT", 1.0, reason="manual", ticker=ticker)


__all__ = [
    "TestFillPricing",
    "TestLiveGate",
    "TestPaperBroker",
    "TestPositionExit",
    "TestRiskGate",
]


class TestAuditTrail:
    """A decision that is not written down did not happen."""

    def test_an_approved_order_records_its_assessment(
        self, executor: OrderExecutor, session: Session, ticker: Ticker
    ):
        from src.database.repositories import RiskRepository

        outcome = executor.execute(buy_request(), approved(), ticker=ticker)
        assessments = RiskRepository(session).assessments_for_order(outcome.order_id)
        assert len(assessments) == 1
        assert outcome.assessment_id == assessments[0].id

    def test_a_rejected_order_is_recorded_too(
        self, executor: OrderExecutor, session: Session, ticker: Ticker
    ):
        from src.database.repositories import RiskRepository
        from src.trading.executor import ExecutionRejected

        with pytest.raises(ExecutionRejected):
            executor.execute(
                buy_request(),
                approved(verdict=RiskVerdict.REJECTED, approved_quantity=0.0),
                ticker=ticker,
            )
        recorded = RiskRepository(session).assessments_for_symbol("BTC/USDT")
        assert recorded, "a refusal with no trace is indistinguishable from a bug"
        assert all(a.verdict == RiskVerdict.REJECTED.value for a in recorded)

    def test_an_exit_records_its_own_reducing_decision(
        self, executor: OrderExecutor, session: Session, ticker: Ticker
    ):
        """The exit must appear in the trail, not vanish as an internal action."""
        from sqlalchemy import select
        from src.core.enums import RiskRule
        from src.database.models.audit import RiskEvent

        executor.execute(buy_request(), approved(), ticker=ticker)
        outcome = executor.close_position("BTC/USDT", 130.0, reason="take_profit", ticker=ticker)
        assert outcome.assessment_id is not None
        rules = set(
            session.scalars(select(RiskEvent.rule).where(RiskEvent.assessment_id == outcome.assessment_id))
        )
        assert RiskRule.POSITION_REDUCING.value in rules
