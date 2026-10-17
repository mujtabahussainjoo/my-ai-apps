"""Database layer tests.

Runs against in-memory SQLite so the suite needs no server. That means these
tests verify SQLAlchemy behaviour and the schema's constraints, not Postgres
itself - the Postgres-specific DDL in ``v001`` is exercised by ``make migrate``
against a real database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from src.core.enums import OrderSide, OrderType, Timeframe, TradingMode
from src.database.base import Base, new_id
from src.database.repositories import (
    CandleRepository,
    OrderRepository,
    PortfolioRepository,
    RiskRepository,
    StrategyStatusRepository,
    TradeRepository,
)

UTC = UTC
START = datetime(2024, 1, 1, tzinfo=UTC)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _rec):
        # SQLite ignores foreign keys unless asked, so the ON DELETE CASCADE
        # behaviour these tests rely on would silently not happen.
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine) -> Session:
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture
def candles():
    from src.schemas.market import Candle

    return [
        Candle(
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            timestamp=START + timedelta(hours=i),
            open=100 + i,
            high=101 + i,
            low=99 + i,
            close=100.5 + i,
            volume=1000.0 + i,
        )
        for i in range(200)
    ]


def make_order(**overrides):
    """Order factory. The schema requires id/order_type/status, and forgetting
    one has produced several confusing fixture errors."""
    from src.schemas.order import Order

    base = {
        "id": new_id(),
        "client_order_id": new_id(),
        "symbol": "BTC/USDT",
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "status": "pending",
        "quantity": 0.1,
    }
    base.update(overrides)
    return Order(**base)


def make_trade(**overrides):
    from src.schemas.trade import Trade

    base = {
        "id": "t-1",
        # Empty rather than a real id: trades carry a foreign key to orders, and
        # most tests here are about the trade, not the order it came from.
        "order_id": "",
        "symbol": "BTC/USDT",
        "side": OrderSide.BUY,
        "strategy": "breakout",
        "quantity": 0.5,
        "entry_price": 100.0,
        "exit_price": 110.0,
        "entry_time": START,
        "exit_time": START + timedelta(hours=3),
        "gross_pnl_usd": 5.0,
        "fees_usd": 0.5,
        "pnl_usd": 4.5,
        "pnl_pct": 4.5,
        "risk_multiple": 2.0,
        "exit_reason": "take_profit",
        "mode": TradingMode.PAPER,
    }
    base.update(overrides)
    return Trade(**base)


# ── schema constraints ─────────────────────────────────────────────────


class TestSchemaConstraints:
    def test_trade_pnl_must_equal_gross_minus_fees(self, session):
        """The ledger's core identity is a database invariant, not a convention."""
        repo = TradeRepository(session)
        with pytest.raises(IntegrityError):
            repo.open_trade(make_trade(pnl_usd=99.0, gross_pnl_usd=5.0, fees_usd=0.5))
        session.rollback()

    def test_negative_fees_are_rejected_by_the_schema(self, session):
        """Defence in depth: the domain schema refuses before the DB is asked."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            make_trade(fees_usd=-1.0, pnl_usd=6.0)

    def test_negative_fees_are_rejected_by_the_database(self, session):
        """The constraint still holds for any write that bypasses the schema."""
        from src.database.models import Trade as TradeRow

        row = TradeRow(
            id="bad-fees",
            symbol="BTC/USDT",
            side="buy",
            mode="paper",
            quantity=1,
            entry_price=100,
            gross_pnl_usd=5,
            fees_usd=-1,
            pnl_usd=6,
            entry_time=START,
        )
        session.add(row)
        with pytest.raises(IntegrityError, match="fees_non_negative"):
            session.flush()
        session.rollback()

    def test_candle_high_must_exceed_low(self, session):
        from src.schemas.market import Candle

        repo = CandleRepository(session)
        bad = Candle(
            symbol="BTC/USDT",
            timeframe=Timeframe.H1,
            timestamp=START,
            open=100,
            high=99,
            low=101,
            close=100,
            volume=10,
        )
        with pytest.raises(IntegrityError):
            repo.upsert_many([bad])
        session.rollback()

    def test_duplicate_candle_updates_rather_than_raises(self, session, candles):
        """Re-downloading overlapping history must be harmless.

        An upsert that raised on conflict would make the download step
        unusable for any history that has already been fetched.
        """
        repo = CandleRepository(session)
        repo.upsert_many(candles[:5])
        session.commit()
        repo.upsert_many(candles[:5])
        session.commit()
        assert repo.count("BTC/USDT", Timeframe.H1) == 5

    def test_duplicate_across_symbols_is_not_a_conflict(self, session):
        """The uniqueness scope is symbol+timeframe+timestamp, not timestamp alone."""
        from src.schemas.market import Candle

        repo = CandleRepository(session)
        for symbol in ("BTC/USDT", "ETH/USDT"):
            repo.upsert_many(
                [
                    Candle(
                        symbol=symbol,
                        timeframe=Timeframe.H1,
                        timestamp=START,
                        open=100,
                        high=101,
                        low=99,
                        close=100,
                        volume=10,
                    )
                ]
            )
        session.commit()
        assert repo.count("BTC/USDT", Timeframe.H1) == 1
        assert repo.count("ETH/USDT", Timeframe.H1) == 1

    def test_balance_cannot_go_negative(self, session):
        repo = PortfolioRepository(session)
        repo.set_balance("USDT", "paper", 100.0)
        session.commit()
        with pytest.raises(ValueError, match="insufficient"):
            repo.debit("USDT", "paper", 150.0)
        session.rollback()

    def test_order_cannot_overfill(self, session):
        from src.schemas.order import OrderFill

        repo = OrderRepository(session)
        order = make_order(client_order_id="k1", quantity=0.1)
        repo.create(order)
        session.commit()
        repo.apply_fill(OrderFill(order_id=order.id, quantity=0.05, price=100.0, fee_usd=0.1))
        with pytest.raises(ValueError, match="over-fill"):
            repo.apply_fill(OrderFill(order_id=order.id, quantity=0.1, price=100.0, fee_usd=0.1))
        session.rollback()


# ── candles ────────────────────────────────────────────────────────────


class TestCandleRepository:
    def test_upsert_is_idempotent(self, session, candles):
        repo = CandleRepository(session)
        repo.upsert_many(candles)
        session.commit()
        repo.upsert_many(candles)
        session.commit()
        assert repo.count("BTC/USDT", Timeframe.H1) == len(candles)

    def test_reinsert_updates_prices(self, session, candles):

        repo = CandleRepository(session)
        repo.upsert_many(candles[:3])
        session.commit()

        corrected = candles[0].model_copy(
            update={"open": 12340.0, "high": 12350.0, "low": 12330.0, "close": 12345.0}
        )
        repo.upsert_many([corrected])
        session.commit()

        stored = repo.get_range("BTC/USDT", Timeframe.H1)
        assert len(stored) == 3, "a correction must update, not duplicate"
        assert stored[0].close == pytest.approx(12345.0)

    def test_impossible_candle_is_refused(self, session, candles):
        """Raising close above high is refused rather than stored.

        Indicators would treat the impossible range as real and produce
        confident nonsense, so the constraint fires.
        """
        repo = CandleRepository(session)
        repo.upsert_many(candles[:1])
        session.commit()
        impossible = candles[0].model_copy(update={"close": 9_999.0})
        with pytest.raises(IntegrityError, match="high_is_max"):
            repo.upsert_many([impossible])
        session.rollback()

    def test_get_range_is_oldest_first(self, session, candles):
        repo = CandleRepository(session)
        repo.upsert_many(candles)
        session.commit()
        rows = repo.get_range("BTC/USDT", Timeframe.H1, limit=10)
        assert [c.timestamp for c in rows] == sorted(c.timestamp for c in rows)

    def test_range_filters_by_time(self, session, candles):
        repo = CandleRepository(session)
        repo.upsert_many(candles)
        session.commit()
        rows = repo.get_range(
            "BTC/USDT", Timeframe.H1, start=START + timedelta(hours=10), end=START + timedelta(hours=20)
        )
        assert len(rows) == 11

    def test_round_trip_preserves_prices(self, session, candles):
        repo = CandleRepository(session)
        repo.upsert_many(candles)
        session.commit()
        stored = repo.get_range("BTC/USDT", Timeframe.H1)
        assert stored[0].close == pytest.approx(candles[0].close)
        assert stored[0].volume == pytest.approx(candles[0].volume)

    def test_gap_detection(self, session):
        from src.schemas.market import Candle

        repo = CandleRepository(session)
        # 1h candles with a 10h hole.
        stamps = [0, 1, 2, 12, 13]
        repo.upsert_many(
            [
                Candle(
                    symbol="ETH/USDT",
                    timeframe=Timeframe.H1,
                    timestamp=START + timedelta(hours=h),
                    open=100,
                    high=101,
                    low=99,
                    close=100,
                    volume=10,
                )
                for h in stamps
            ]
        )
        session.commit()
        assert repo.has_gap("ETH/USDT", Timeframe.H1) is True

    def test_no_gap_in_contiguous_series(self, session, candles):
        repo = CandleRepository(session)
        repo.upsert_many(candles)
        session.commit()
        assert repo.has_gap("BTC/USDT", Timeframe.H1) is False

    def test_chunked_bulk_insert(self, session, candles):
        """More rows than CHCHUNK, to exercise the chunking path."""
        repo = CandleRepository(session)
        repo.upsert_many(candles)
        session.commit()
        assert repo.count("BTC/USDT", Timeframe.H1) == 200


# ── orders ─────────────────────────────────────────────────────────────


class TestOrderRepository:
    def test_replay_returns_the_original_order(self, session):
        repo = OrderRepository(session)
        first = repo.create(make_order(client_order_id="same-key"))
        session.commit()
        second = repo.create(make_order(client_order_id="same-key"))
        session.commit()
        assert first.id == second.id

    def test_volume_weighted_average_price(self, session):
        from src.schemas.order import OrderFill

        repo = OrderRepository(session)
        order = repo.create(make_order(client_order_id="k2", quantity=0.3))
        session.commit()
        repo.apply_fill(OrderFill(order_id=order.id, quantity=0.1, price=100.0, fee_usd=0.1))
        repo.apply_fill(OrderFill(order_id=order.id, quantity=0.2, price=110.0, fee_usd=0.2))
        session.commit()

        row = repo.get(order.id)
        assert float(row.filled_quantity) == pytest.approx(0.3)
        assert float(row.fee_usd) == pytest.approx(0.3)
        # (100*0.1 + 110*0.2) / 0.3
        assert float(row.average_price) == pytest.approx(106.6667, abs=1e-3)

    def test_fractional_fills_do_not_trip_the_overfill_guard(self, session):
        """0.1 + 0.2 != 0.3 in binary floating point.

        Three small fills that legitimately total the order quantity must be
        accepted; the guard exists to catch a real over-fill, not float noise.
        """
        from src.schemas.order import OrderFill

        repo = OrderRepository(session)
        order = repo.create(make_order(quantity=0.3))
        session.commit()
        for qty in (0.1, 0.1, 0.1):
            repo.apply_fill(OrderFill(order_id=order.id, quantity=qty, price=100.0, fee_usd=0.01))
        session.commit()
        assert float(repo.get(order.id).filled_quantity) == pytest.approx(0.3)

    def test_a_real_overfill_is_still_refused(self, session):
        from src.schemas.order import OrderFill

        repo = OrderRepository(session)
        order = repo.create(make_order(quantity=0.1))
        session.commit()
        with pytest.raises(ValueError, match="over-fill"):
            repo.apply_fill(OrderFill(order_id=order.id, quantity=0.11, price=100.0, fee_usd=0.01))
        session.rollback()

    def test_fill_for_unknown_order_is_rejected(self, session):
        from src.schemas.order import OrderFill

        repo = OrderRepository(session)
        with pytest.raises(ValueError, match="unknown order"):
            repo.apply_fill(OrderFill(order_id="nope", quantity=1, price=100, fee_usd=0))


# ── portfolio ──────────────────────────────────────────────────────────


class TestPortfolioRepository:
    def test_credit_and_debit(self, session):
        repo = PortfolioRepository(session)
        repo.credit("USDT", "paper", 1000.0)
        repo.debit("USDT", "paper", 250.0)
        assert repo.cash_usd("paper") == pytest.approx(750.0)

    def test_paper_and_live_balances_are_separate(self, session):
        repo = PortfolioRepository(session)
        repo.set_balance("USDT", "paper", 10_000.0)
        repo.set_balance("USDT", "live", 500.0)
        assert repo.cash_usd("paper") == pytest.approx(10_000.0)
        assert repo.cash_usd("live") == pytest.approx(500.0)

    def test_position_upsert_is_per_symbol_and_mode(self, session):
        from src.schemas.portfolio import Position

        repo = PortfolioRepository(session)
        repo.upsert_position(
            Position(
                symbol="BTC/USDT", quantity=1.0, entry_price=100.0, side=OrderSide.BUY, mode=TradingMode.PAPER
            )
        )
        repo.upsert_position(
            Position(
                symbol="BTC/USDT", quantity=2.0, entry_price=105.0, side=OrderSide.BUY, mode=TradingMode.PAPER
            )
        )
        session.commit()
        positions = repo.get_positions("paper")
        assert len(positions) == 1
        assert positions[0].quantity == pytest.approx(2.0)

    def test_short_unrealized_pnl(self, session):
        from src.schemas.portfolio import Position

        repo = PortfolioRepository(session)
        repo.upsert_position(
            Position(
                symbol="BTC/USDT",
                quantity=1.0,
                entry_price=100.0,
                side=OrderSide.SELL,
                current_price=90.0,
                mode=TradingMode.PAPER,
            )
        )
        session.commit()
        # A short that fell 10 points is +10, not -10.
        assert repo.unrealized_pnl_usd("paper") == pytest.approx(10.0)

    def test_snapshot_includes_positions_and_exposure(self, session):
        from src.schemas.portfolio import Position

        repo = PortfolioRepository(session)
        repo.set_balance("USDT", "paper", 5_000.0)
        repo.upsert_position(
            Position(
                symbol="BTC/USDT",
                quantity=1.0,
                entry_price=4_000.0,
                current_price=4_000.0,
                side=OrderSide.BUY,
                mode=TradingMode.PAPER,
            )
        )
        session.commit()

        snapshot = repo.build_snapshot("paper")
        repo.record_snapshot(snapshot)
        session.commit()

        assert snapshot.open_positions == 1
        assert snapshot.positions_value_usd == pytest.approx(4_000.0)
        assert snapshot.equity_usd == pytest.approx(9_000.0)
        assert snapshot.exposure_pct == pytest.approx(4_000.0 / 9_000.0 * 100)

    def test_equity_curve_round_trip(self, session):
        from src.schemas.portfolio import PortfolioSnapshot

        repo = PortfolioRepository(session)
        for i in range(5):
            repo.record_snapshot(
                PortfolioSnapshot(
                    equity_usd=10_000.0 + i * 10,
                    cash_usd=10_000.0,
                    as_of=START + timedelta(hours=i),
                )
            )
        session.commit()
        curve = repo.equity_curve("paper")
        assert [v for _, v in curve] == [10_000.0 + i * 10 for i in range(5)]


# ── risk ───────────────────────────────────────────────────────────────


class TestRiskRepository:
    def _assessment(self, passed: bool = True):
        from src.core.enums import RiskLevel, RiskVerdict, Severity
        from src.schemas.risk import RiskAssessment, RiskCheck

        return RiskAssessment(
            verdict=RiskVerdict.APPROVED if passed else RiskVerdict.REJECTED,
            approved_quantity=0.1 if passed else 0.0,
            approved_notional_usd=1000.0 if passed else 0.0,
            approved_risk_usd=50.0 if passed else 0.0,
            risk_level=RiskLevel.LOW,
            checks=[
                RiskCheck(
                    rule="MAX_POSITION_SIZE",
                    passed=passed,
                    message="ok" if passed else "too big",
                    severity=Severity.CRITICAL if not passed else Severity.INFO,
                    observed=0.5,
                    limit=0.25,
                ),
                RiskCheck(rule="CASH_AVAILABLE", passed=True, message="ok", severity=Severity.INFO),
            ],
        )

    def test_assessment_writes_one_event_per_check(self, session):
        from src.database.models import RiskEvent

        repo = RiskRepository(session)
        repo.record_assessment(
            self._assessment(passed=False),
            symbol="BTC/USDT",
            side="buy",
            mode="paper",
            requested_quantity=0.5,
        )
        session.commit()

        events = session.query(RiskEvent).all()
        assert len(events) == 2, "passing checks must be recorded too"
        assert sum(1 for e in events if not e.passed) == 1

    def test_failed_checks_query(self, session):
        repo = RiskRepository(session)
        repo.record_assessment(
            self._assessment(passed=False),
            symbol="BTC/USDT",
            side="buy",
            mode="paper",
            requested_quantity=0.5,
        )
        session.commit()
        failed = repo.failed_checks()
        assert len(failed) == 1
        assert failed[0].rule == "MAX_POSITION_SIZE"

    def test_rejection_rate(self, session):
        repo = RiskRepository(session)
        since = START
        for i in range(3):
            repo.record_assessment(
                self._assessment(passed=i > 0),
                symbol="BTC/USDT",
                side="buy",
                mode="paper",
                requested_quantity=0.5,
            )
        session.commit()
        # i=0 is the only rejection, so 1 of 3.
        assert repo.rejection_rate(since) == pytest.approx(1 / 3)

    def test_breaker_logged(self, session):
        repo = RiskRepository(session)
        repo.log_breaker("daily_loss", "engaged", "limit hit", value=-500, threshold=-300)
        session.commit()
        assert len(repo.breaker_history("daily_loss")) == 1


# ── strategy gate ──────────────────────────────────────────────────────


class TestStrategyStatusRepository:
    def test_unknown_strategy_is_not_qualified(self, session):
        repo = StrategyStatusRepository(session)
        assert repo.is_qualified("never-heard-of-it") is False
        assert repo.is_qualified(None) is False

    def test_qualified_flag_round_trip(self, session):
        repo = StrategyStatusRepository(session)
        repo.set("breakout", "qualified", qualified=True)
        session.commit()
        assert repo.is_qualified("breakout") is True
        assert repo.qualified_strategies() == ["breakout"]

    def test_demotion_revokes_qualification(self, session):
        repo = StrategyStatusRepository(session)
        repo.set("momentum", "qualified", qualified=True)
        session.commit()
        repo.set("momentum", "suspended", qualified=False)
        session.commit()
        assert repo.is_qualified("momentum") is False


# ── numeric fidelity ───────────────────────────────────────────────────


class TestNumericFidelity:
    def test_money_survives_a_database_round_trip(self, session):
        """Floats would drift here; NUMERIC is why the column is not a float."""
        repo = TradeRepository(session)
        repo.open_trade(make_trade(id="precise", pnl_usd=0.1, gross_pnl_usd=0.3, fees_usd=0.2))
        session.commit()
        session.expire_all()

        stored = repo.get("precise")
        assert Decimal(stored.pnl_usd) == Decimal("0.1")
        assert Decimal(stored.fees_usd) == Decimal("0.2")

    def test_sum_of_trades_is_exact(self, session):
        """Money survives a SUM without binary-float drift.

        SQLite stores NUMERIC as REAL, so the raw SQL sum really is
        0.30000000000000004. The result comes back exact because SQLAlchemy's
        NUMERIC result processor rounds to the column's declared scale of 8.
        True NUMERIC arithmetic is proven in tests/integration/test_postgres.py.
        """
        repo = TradeRepository(session)
        for i in range(3):
            repo.open_trade(make_trade(id=f"n{i}", pnl_usd=0.1, gross_pnl_usd=0.3, fees_usd=0.2))
        session.commit()
        assert Decimal(str(repo.realized_pnl())) == Decimal("0.3")
