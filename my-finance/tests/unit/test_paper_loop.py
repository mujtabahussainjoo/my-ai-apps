"""Paper-loop tests.

The loop is where the layers meet, so the tests focus on the seams: that an
unqualified strategy cannot trade, that a position is not quietly doubled, that
a stop is honoured on the side the position could actually be sold at, and that
every signal that reaches the gate is recorded first.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import src.database.models  # noqa: F401 - registers the mappers
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from src.core.config import Settings
from src.core.enums import StrategyStatus, Timeframe, TradingMode
from src.database.base import Base
from src.database.repositories import (
    PortfolioRepository,
    SignalRepository,
    StrategyStatusRepository,
)
from src.database.seed import ensure_reference_data
from src.schemas.base import utcnow
from src.schemas.market import Candle, IndicatorSnapshot, Ticker
from src.schemas.signal import Signal, SignalAction, SignalScore
from src.trading.paper_loop import CycleResult, PaperTradingLoop

SYMBOL = "BTC/USDT"


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
def settings() -> Settings:
    return Settings(
        trading_mode="paper",
        llm_enabled=False,
        trading_symbols=[SYMBOL],
        trading_strategies=["breakout"],
        market_data_allow_synthetic=False,
        starting_equity_usd=10_000.0,
    )


@pytest.fixture
def qualified(session: Session) -> StrategyStatusRepository:
    statuses = StrategyStatusRepository(session)
    statuses.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
    session.commit()
    return statuses


@pytest.fixture
def loop(session: Session, settings: Settings) -> PaperTradingLoop:
    ensure_reference_data(session, settings)
    session.commit()
    return PaperTradingLoop(session, settings)


def make_candles(count: int = 200, *, start_price: float = 100.0) -> list[Candle]:
    """A rising series, enough history for indicator warm-up."""
    candles = []
    price = start_price
    for i in range(count):
        price *= 1.001
        candles.append(
            Candle(
                symbol=SYMBOL,
                timeframe=Timeframe.H1,
                timestamp=1700000000000 + i * 3_600_000,
                open=price * 0.999,
                high=price * 1.002,
                low=price * 0.998,
                close=price,
                volume=1_000.0,
            )
        )
    return candles


def make_signal(
    action: SignalAction = SignalAction.BUY,
    *,
    entry: float = 100.0,
    stop_loss: float | None = 96.5,
    take_profit: float | None = 110.0,
) -> Signal:
    return Signal(
        symbol=SYMBOL,
        timeframe=Timeframe.H1,
        strategy="breakout",
        action=action,
        confidence=0.8,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        score=SignalScore(total=0.8, components={"trend": 0.8}),
        created_at=utcnow(),
    )


def indicators(atr: float = 3.0) -> IndicatorSnapshot:
    return IndicatorSnapshot(
        symbol=SYMBOL,
        timeframe=Timeframe.H1,
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        close=100.0,
        atr=atr,
    )


# ── Seeding ─────────────────────────────────────────────────────────────────


class TestSeeding:
    def test_seeding_creates_strategies_as_candidates(self, session: Session, settings: Settings):
        ensure_reference_data(session, settings)
        statuses = StrategyStatusRepository(session)
        assert statuses.get("breakout").status == StrategyStatus.CANDIDATE
        assert statuses.get("breakout").qualified is False

    def test_seeding_never_marks_a_strategy_tradeable(self, session: Session, settings: Settings):
        """The promotion gate must not be bypassable by provisioning data."""
        ensure_reference_data(session, settings)
        session.commit()
        assert StrategyStatusRepository(session).qualified_strategies() == []

    def test_seeding_is_idempotent(self, session: Session, settings: Settings):
        first = ensure_reference_data(session, settings)
        second = ensure_reference_data(session, settings)
        assert first["strategies"] > 0
        assert second == {"strategies": 0, "balances": 0}

    def test_seeding_creates_the_starting_balance(self, session: Session, settings: Settings):
        ensure_reference_data(session, settings)
        balance = PortfolioRepository(session).get_balance("USDT", TradingMode.PAPER.value)
        assert balance.free == pytest.approx(10_000.0)


# ── Signal persistence ──────────────────────────────────────────────────────


class TestSignalPersistence:
    def test_a_signal_survives_a_database_round_trip(self, session: Session, settings: Settings):
        ensure_reference_data(session, settings)
        repo = SignalRepository(session)
        signal = make_signal()
        signal_id = repo.record(signal)
        session.commit()

        loaded = repo.get(signal_id)
        assert loaded is not None
        assert loaded.symbol == SYMBOL
        assert loaded.action is SignalAction.BUY
        assert loaded.entry == pytest.approx(100.0)
        assert loaded.stop_loss == pytest.approx(96.5)

    def test_scores_survive_json_serialisation(self, session: Session, settings: Settings):
        """computed_at is a datetime; the JSON column needs a JSON-native dump."""
        ensure_reference_data(session, settings)
        repo = SignalRepository(session)
        signal_id = repo.record(make_signal())
        session.commit()
        loaded = repo.get(signal_id)
        assert loaded.score is not None
        assert loaded.score.total == pytest.approx(0.8)


# ── Qualification gate ──────────────────────────────────────────────────────


class TestQualificationGate:
    def test_an_unqualified_strategy_produces_no_order(self, loop: PaperTradingLoop, settings: Settings):
        """Every seeded strategy starts CANDIDATE, so the loop stays flat."""
        result = CycleResult()
        loop._handle_signal(
            make_signal(), Ticker(symbol=SYMBOL, last=100.0, bid=99.9, ask=100.1), indicators(), result
        )
        assert result.orders_sent == 0
        assert result.orders_rejected == 1
        assert loop.portfolio.get_positions(TradingMode.PAPER.value) == []

    def test_an_unknown_strategy_is_treated_as_unqualified(self, loop: PaperTradingLoop):
        assert loop.strategy_status("does_not_exist") is StrategyStatus.CANDIDATE

    def test_a_stored_string_status_is_converted_to_the_enum(
        self, loop: PaperTradingLoop, qualified: StrategyStatusRepository
    ):
        """The ORM column is a plain string; the engine needs the enum."""
        assert loop.strategy_status("breakout") is StrategyStatus.QUALIFIED

    def test_an_unrecognised_status_fails_closed(self, loop: PaperTradingLoop):
        """Defence in depth: the column is CHECK-constrained, but a row loaded
        from an older schema could still hold a value the enum rejects."""
        row = loop.strategies.get("breakout")
        row.status = "not_a_real_status"  # no flush: the CHECK would refuse it
        assert loop.strategy_status("breakout") is StrategyStatus.CANDIDATE

    def test_the_column_refuses_a_status_the_enum_does_not_know(self, loop):
        """The database rejects it too, so a bad value cannot be written at all."""
        import pytest as _pytest
        from sqlalchemy.exc import IntegrityError

        row = loop.strategies.get("breakout")
        row.status = "not_a_real_status"
        with _pytest.raises(IntegrityError):
            loop.session.flush()
        loop.session.rollback()


# ── Entry behaviour ─────────────────────────────────────────────────────────


class TestEntry:
    def test_a_position_is_not_pyramided_each_cycle(
        self, loop: PaperTradingLoop, qualified: StrategyStatusRepository
    ):
        """A still-bullish strategy must not re-buy into its own position."""
        ticker = Ticker(symbol=SYMBOL, last=100.0, bid=99.9, ask=100.1)
        result = CycleResult()

        loop._handle_signal(make_signal(), ticker, indicators(), result)
        assert result.orders_sent == 1

        loop.session.commit()
        positions = loop.portfolio.get_positions(TradingMode.PAPER.value)
        assert len(positions) == 1
        first_quantity = positions[0].quantity

        second = CycleResult()
        loop._handle_signal(make_signal(), ticker, indicators(), second)
        assert second.orders_sent == 0

        loop.session.commit()
        still_here = loop.portfolio.get_positions(TradingMode.PAPER.value)
        assert len(still_here) == 1
        assert still_here[0].quantity == pytest.approx(first_quantity)

    def test_the_signal_is_recorded_before_the_order(
        self, loop: PaperTradingLoop, qualified: StrategyStatusRepository
    ):
        """Order lineage depends on the signal existing first."""
        before = len(loop.signals.recent())
        loop._handle_signal(
            make_signal(), Ticker(symbol=SYMBOL, last=100.0, bid=99.9, ask=100.1), indicators(), CycleResult()
        )
        loop.session.commit()
        assert len(loop.signals.recent()) == before + 1
        assert loop.signals.recent()[0].strategy == "breakout"


# ── Exits ───────────────────────────────────────────────────────────────────


def open_long_position(loop: PaperTradingLoop) -> None:
    """Put a long position on the book at a known price."""
    loop._handle_signal(
        make_signal(entry=100.0, stop_loss=96.5, take_profit=110.0),
        Ticker(symbol=SYMBOL, last=100.0, bid=99.9, ask=100.1),
        indicators(),
        CycleResult(),
    )
    loop.session.commit()


class TestExits:
    def test_a_stop_is_honoured_when_the_bid_reaches_it(self, loop: PaperTradingLoop, qualified):
        open_long_position(loop)
        assert len(loop.portfolio.get_positions(TradingMode.PAPER.value)) == 1

        # Bid has fallen through the stop: the position must be closed.
        # The method returns the count; run_cycle is what files it on the result.
        closed = loop._manage_open_positions(
            {SYMBOL: Ticker(symbol=SYMBOL, last=95.0, bid=95.0, ask=95.2)}, CycleResult()
        )
        loop.session.commit()

        assert closed == 1
        assert loop.portfolio.get_positions(TradingMode.PAPER.value) == []

    def test_a_take_profit_closes_the_position(self, loop: PaperTradingLoop, qualified):
        open_long_position(loop)
        closed = loop._manage_open_positions(
            {SYMBOL: Ticker(symbol=SYMBOL, last=112.0, bid=111.8, ask=112.2)}, CycleResult()
        )
        loop.session.commit()
        assert closed == 1
        assert loop.portfolio.get_positions(TradingMode.PAPER.value) == []

    def test_a_price_inside_the_band_leaves_the_position_open(self, loop: PaperTradingLoop, qualified):
        open_long_position(loop)
        closed = loop._manage_open_positions(
            {SYMBOL: Ticker(symbol=SYMBOL, last=105.0, bid=104.9, ask=105.1)}, CycleResult()
        )
        loop.session.commit()
        assert closed == 0
        assert len(loop.portfolio.get_positions(TradingMode.PAPER.value)) == 1

    def test_a_stopping_position_realises_a_loss(self, loop: PaperTradingLoop, qualified):
        """A stop must cost money, not quietly break even."""
        open_long_position(loop)
        before = loop.portfolio.build_snapshot(TradingMode.PAPER.value).equity_usd

        loop._manage_open_positions(
            {SYMBOL: Ticker(symbol=SYMBOL, last=95.0, bid=95.0, ask=95.2)}, CycleResult()
        )
        loop.session.commit()
        after = loop.portfolio.build_snapshot(TradingMode.PAPER.value).equity_usd
        assert after < before


# ── Candle handling ─────────────────────────────────────────────────────────


class TestCandleLoading:
    def test_candles_are_returned_oldest_first(self, loop: PaperTradingLoop, settings: Settings):
        """Indicators are order-dependent, so ordering is part of the contract."""
        candles = make_candles(5)
        loop.candles.upsert_many(candles)
        loop.session.commit()

        stored = loop.candles.get_range(SYMBOL, Timeframe.H1, limit=300, ascending=False)
        stored.reverse()
        assert [c.close for c in stored] == sorted(c.close for c in stored)

    def test_indicators_are_built_from_stored_candles(self, loop: PaperTradingLoop):
        loop.candles.upsert_many(make_candles(200))
        loop.session.commit()

        loaded, snapshot = loop._load_analysis_data(SYMBOL)
        assert loaded is not None and snapshot is not None
        assert snapshot.atr is not None and snapshot.atr > 0
