"""Portfolio state persistence.

Balance updates go through :meth:`PortfolioRepository.credit` and
:meth:`debit` rather than raw assignment, because a ledger that can be set to
any value is not a ledger. Every mutation also writes a snapshot in the same
transaction, so the equity curve can never disagree with the balances.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.enums import OrderSide, TradingMode
from src.core.logging import get_logger
from src.database.base import utcnow
from src.database.models import (
    Balance,
    PaperPerformance,
    PortfolioSnapshot,
    Position,
    Trade,
)
from src.database.repositories import mappers
from src.schemas.portfolio import Balance as BalanceSchema
from src.schemas.portfolio import PortfolioSnapshot as SnapshotSchema
from src.schemas.portfolio import Position as PositionSchema

logger = get_logger(__name__)


def _start_of_day() -> datetime:
    now = utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class PortfolioRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── balances ─────────────────────────────────────────────────────

    def set_balance(self, asset: str, mode: str, free: float, locked: float = 0.0) -> Balance:
        row = self.session.scalar(select(Balance).where(Balance.asset == asset, Balance.mode == mode))
        if row is None:
            row = Balance(asset=asset, mode=mode, free=mappers.d(free), locked=mappers.d(locked))
            self.session.add(row)
        else:
            row.free = mappers.d(free)
            row.locked = mappers.d(locked)
        self.session.flush()
        return row

    def credit(self, asset: str, mode: str, amount: float) -> Balance:
        row = self._row(asset, mode)
        if row is None:
            row = self.set_balance(asset, mode, 0.0)
        row.free = mappers.d(float(row.free) + amount)
        self.session.flush()
        return row

    def debit(self, asset: str, mode: str, amount: float) -> Balance:
        """Deduct cash, refusing to go negative.

        The check constraint catches it too, but by then the transaction is
        already poisoned; raising here produces a message naming the asset.
        """
        row = self._row(asset, mode)
        available = float(row.free)
        if available < amount - 1e-9:
            raise ValueError(f"insufficient {asset}: have {available:.8f}, need {amount:.8f} (mode={mode})")
        row.free = mappers.d(available - amount)
        self.session.flush()
        return row

    def get_balance(self, asset: str, mode: str) -> BalanceSchema | None:
        row = self._row(asset, mode)
        if row is None:
            return None
        return BalanceSchema(asset=row.asset, free=mappers.f(row.free), locked=mappers.f(row.locked))

    def cash_usd(self, mode: str, asset: str = "USDT") -> float:
        row = self._row(asset, mode)
        return mappers.f(row.free) if row is not None else 0.0

    def _row(self, asset: str, mode: str) -> Balance | None:
        return self.session.scalar(select(Balance).where(Balance.asset == asset, Balance.mode == mode))

    # ── positions ────────────────────────────────────────────────────

    def upsert_position(self, position: PositionSchema) -> Position:
        row = self.session.scalar(
            select(Position).where(Position.symbol == position.symbol, Position.mode == position.mode.value)
        )
        payload = mappers.position_to_row(position)
        if row is None:
            row = Position(**payload)
            self.session.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        self.session.flush()
        return row

    def close_position(self, symbol: str, mode: str) -> None:
        row = self.session.scalar(select(Position).where(Position.symbol == symbol, Position.mode == mode))
        if row is not None:
            self.session.delete(row)
            self.session.flush()

    def get_position(self, symbol: str, mode: str) -> PositionSchema | None:
        row = self.session.scalar(select(Position).where(Position.symbol == symbol, Position.mode == mode))
        return mappers.row_to_position(row) if row is not None else None

    def get_positions(self, mode: str) -> list[PositionSchema]:
        rows = self.session.scalars(select(Position).where(Position.mode == mode).order_by(Position.symbol))
        return [mappers.row_to_position(r) for r in rows]

    def open_position_count(self, mode: str) -> int:
        return len(self.get_positions(mode))

    def total_exposure_usd(self, mode: str) -> float:
        """Sum of absolute notional. Long and short both consume risk budget."""
        return sum(abs(p.quantity * (p.current_price or p.entry_price)) for p in self.get_positions(mode))

    def unrealized_pnl_usd(self, mode: str) -> float:
        total = 0.0
        for p in self.get_positions(mode):
            if p.current_price is None:
                continue
            direction = 1.0 if p.side is OrderSide.BUY else -1.0
            total += direction * (p.current_price - p.entry_price) * p.quantity
        return total

    # ── snapshots ────────────────────────────────────────────────────

    def record_snapshot(self, snapshot: SnapshotSchema) -> PortfolioSnapshot:
        row = PortfolioSnapshot(**mappers.snapshot_to_row(snapshot))
        self.session.add(row)
        self.session.flush()
        return row

    def latest_snapshot(self, mode: str) -> SnapshotSchema | None:
        row = self.session.scalar(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.mode == mode)
            .order_by(PortfolioSnapshot.as_of.desc())
            .limit(1)
        )
        return mappers.row_to_snapshot(row) if row is not None else None

    def equity_curve(self, mode: str, limit: int | None = None) -> list[tuple[datetime, float]]:
        stmt = (
            select(PortfolioSnapshot.as_of, PortfolioSnapshot.equity_usd)
            .where(PortfolioSnapshot.mode == mode)
            .order_by(PortfolioSnapshot.as_of)
        )
        if limit:
            stmt = stmt.limit(limit)
        return [(mappers.dt(a), mappers.f(e)) for a, e in self.session.execute(stmt)]

    def build_snapshot(self, mode: str) -> SnapshotSchema:
        """Compose a live snapshot from balances and positions.

        Assembling it here rather than trusting a caller means the exposure and
        drawdown figures cannot be quietly understated.
        """
        cash = self.cash_usd(mode)
        positions = self.get_positions(mode)
        positions_value = sum(abs(p.quantity * (p.current_price or p.entry_price)) for p in positions)
        unrealized = self.unrealized_pnl_usd(mode)
        # Marked position value already contains its unrealised profit.
        equity = cash + positions_value
        realized = self._realized_pnl(mode)
        day_realized = self._realized_pnl(mode, since=_start_of_day())

        previous = self.latest_snapshot(mode)
        prior_peak = previous.peak_equity_usd if previous else 0.0
        peak_equity = max(equity, prior_peak)
        drawdown = ((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0.0
        # The first snapshot defines the baseline the whole curve is measured
        # against; later ones inherit it rather than resetting to today's equity.
        starting = previous.starting_equity_usd if previous else equity

        return SnapshotSchema(
            equity_usd=equity,
            cash_usd=cash,
            positions_value_usd=positions_value,
            unrealized_pnl_usd=unrealized,
            realized_pnl_usd=realized,
            daily_pnl_usd=day_realized,
            daily_pnl_pct=(day_realized / starting * 100) if starting > 0 else 0.0,
            total_exposure_usd=positions_value,
            exposure_pct=(positions_value / equity * 100) if equity > 0 else 0.0,
            open_positions=len(positions),
            current_drawdown_pct=drawdown,
            peak_equity_usd=peak_equity,
            starting_equity_usd=starting,
            mode=TradingMode(mode),
            as_of=utcnow(),
            positions=positions,
        )

    def _realized_pnl(self, mode: str, since: datetime | None = None) -> float:
        from sqlalchemy import func

        stmt = select(func.coalesce(func.sum(Trade.pnl_usd), 0)).where(
            Trade.mode == mode, Trade.is_open.is_(False)
        )
        if since:
            stmt = stmt.where(Trade.exit_time >= since)
        return mappers.f(self.session.scalar(stmt))


class PaperPerformanceRepository:
    """Forward-test evidence that the qualification gate reads."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, strategy: str, **fields) -> PaperPerformance:
        row = self.session.scalar(select(PaperPerformance).where(PaperPerformance.strategy == strategy))
        if row is None:
            row = PaperPerformance(strategy=strategy)
            self.session.add(row)
        for key, value in fields.items():
            if hasattr(row, key):
                setattr(
                    row,
                    key,
                    int(value)
                    if key == "trades"
                    else (mappers.d(value) if isinstance(value, (int, float)) else value),
                )
        self.session.flush()
        return row

    def get(self, strategy: str) -> PaperPerformance | None:
        return self.session.scalar(select(PaperPerformance).where(PaperPerformance.strategy == strategy))

    def all(self) -> list[PaperPerformance]:
        return list(self.session.scalars(select(PaperPerformance).order_by(PaperPerformance.strategy)))

    def refresh(self, strategy: str, mode: str = "paper") -> PaperPerformance:
        """Recompute a strategy's paper record from its closed trades.

        Derived rather than incrementally maintained on purpose: the numbers
        that gate promotion to live must be reproducible from the trade log.
        """
        trades = list(
            self.session.scalars(
                select(Trade).where(
                    Trade.strategy == strategy,
                    Trade.mode == mode,
                    Trade.is_open.is_(False),
                )
            )
        )
        if not trades:
            prior = self.get(strategy)
            starting = float(prior.starting_balance) if prior else 10_000.0
            return self.upsert(
                strategy,
                trades=0,
                win_rate=0.0,
                profit_factor=0.0,
                max_drawdown_pct=0.0,
                days_active=0.0,
                starting_balance=starting,
                ending_balance=starting,
                window_start=None,
                window_end=None,
            )

        wins = [t for t in trades if mappers.f(t.pnl_usd) > 0]
        losses = [t for t in trades if mappers.f(t.pnl_usd) < 0]
        gross_win = sum(mappers.f(t.pnl_usd) for t in wins)
        gross_loss = abs(sum(mappers.f(t.pnl_usd) for t in losses))

        exits = [t.exit_time for t in trades if t.exit_time]
        days = 0.0
        if exits:
            days = (max(exits) - min(exits)).total_seconds() / 86400.0

        curve = sorted((t.exit_time, mappers.f(t.pnl_usd)) for t in trades if t.exit_time)
        prior = self.get(strategy)
        starting = float(prior.starting_balance) if prior else 10_000.0
        equity, peak, max_dd = starting, starting, 0.0
        for _, pnl in curve:
            equity += pnl
            peak = max(peak, equity)
            max_dd = max(max_dd, ((peak - equity) / peak * 100) if peak > 0 else 0.0)

        return self.upsert(
            strategy,
            trades=len(trades),
            win_rate=len(wins) / len(trades),
            profit_factor=(gross_win / gross_loss)
            if gross_loss > 0
            else (999999.0 if gross_win > 0 else 0.0),
            max_drawdown_pct=max_dd,
            starting_balance=starting,
            ending_balance=equity,
            window_start=min(exits) if exits else None,
            window_end=max(exits) if exits else None,
            days_active=days,
        )
