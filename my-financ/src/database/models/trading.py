"""Trading tables: signals, orders, fills, trades, positions, balances.

Two rules are enforced by the schema rather than left to application code:

* ``orders.client_order_id`` is unique. It carries the idempotency key, so a
  retried request cannot create a second live order.
* ``balances`` and ``positions`` are unique per ``(asset, mode)``. Paper and live
  capital must never be able to see each other's rows.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import (
    MONEY,
    PRICE,
    QUANTITY,
    USD,
    VOLUME,
    Base,
    JSONType,
    TimestampMixin,
    new_id,
)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(16), default="1.0", nullable=False)
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float] = mapped_column(MONEY, nullable=False)
    entry: Mapped[float] = mapped_column(PRICE, nullable=False)
    stop_loss: Mapped[float | None] = mapped_column(PRICE)
    take_profit: Mapped[float | None] = mapped_column(PRICE)
    atr: Mapped[float | None] = mapped_column(PRICE)
    #: Confidence breakdown and rationale text. JSONB so a new scoring dimension
    #: does not need a migration.
    score: Mapped[dict | None] = mapped_column(JSONType)
    rationale: Mapped[list | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Lifecycle of the signal's *decision*, not its generation. ``pending`` is
    #: the only state with work behind it: the worker polls for exactly those
    #: rows. ``rejected`` and ``ignored`` keep the outcome visible even though
    #: neither produced an order.
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Set only when the signal became an order. Stays null on rejection, which
    #: is exactly the case that used to leave no trace.
    order_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("orders.id", ondelete="SET NULL"))
    reject_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("action IN ('buy','sell','hold')", name="action_valid"),
        CheckConstraint(
            "status IN ('pending','executed','rejected','ignored')", name="signal_status_valid"
        ),
        Index("ix_signals_symbol_created", "symbol", "created_at"),
        Index("ix_signals_strategy_created", "strategy", "created_at"),
    )


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    #: Doubles as the exchange client order id and the idempotency key.
    client_order_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    signal_id: Mapped[str | None] = mapped_column(String(36))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), default="market", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    quantity: Mapped[float] = mapped_column(QUANTITY, nullable=False)
    filled_quantity: Mapped[float] = mapped_column(QUANTITY, default=0.0, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(PRICE)
    average_price: Mapped[float | None] = mapped_column(PRICE)
    fee_usd: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)

    stop_loss: Mapped[float | None] = mapped_column(PRICE)
    take_profit: Mapped[float | None] = mapped_column(PRICE)
    strategy: Mapped[str | None] = mapped_column(String(64))
    leverage: Mapped[float] = mapped_column(MONEY, default=1.0, nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[dict | None] = mapped_column(JSONType)

    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="side_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("filled_quantity >= 0", name="filled_non_negative"),
        # Over-filling an order is how a bug becomes a loss: cap it in the database.
        CheckConstraint("filled_quantity <= quantity", name="filled_within_quantity"),
        Index("ix_orders_symbol_created", "symbol", "created_at"),
        Index("ix_orders_status_mode", "status", "mode"),
    )


class OrderFill(Base):
    __tablename__ = "order_fills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[float] = mapped_column(QUANTITY, nullable=False)
    price: Mapped[float] = mapped_column(PRICE, nullable=False)
    fee_usd: Mapped[float] = mapped_column(USD, nullable=False)
    slippage_bps: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price > 0", name="price_positive"),
        Index("ix_fills_order", "order_id"),
        Index("ix_fills_filled_at", "filled_at"),
    )


class Trade(Base):
    """A round trip. ``exit_*`` stays null while the trade is open."""

    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("orders.id"))
    signal_id: Mapped[str | None] = mapped_column(String(36))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    strategy: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    quantity: Mapped[float] = mapped_column(QUANTITY, nullable=False)
    entry_price: Mapped[float] = mapped_column(PRICE, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(PRICE)

    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Gross is before fees; pnl is the authoritative net figure.
    gross_pnl_usd: Mapped[float] = mapped_column(USD, nullable=False)
    fees_usd: Mapped[float] = mapped_column(USD, nullable=False)
    pnl_usd: Mapped[float] = mapped_column(USD, nullable=False)
    pnl_pct: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)

    initial_risk_per_unit: Mapped[float | None] = mapped_column(PRICE)
    risk_multiple: Mapped[float | None] = mapped_column(MONEY)
    planned_risk_reward: Mapped[float | None] = mapped_column(MONEY)
    exit_reason: Mapped[str | None] = mapped_column(String(24))
    notes: Mapped[str | None] = mapped_column(Text)

    is_open: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    peak_price: Mapped[float | None] = mapped_column(PRICE)
    initial_stop: Mapped[float | None] = mapped_column(PRICE)
    trailing_stop: Mapped[float | None] = mapped_column(PRICE)

    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="side_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("fees_usd >= 0", name="fees_non_negative"),
        CheckConstraint(
            # Tolerance, not equality. On PostgreSQL (true NUMERIC) the two sides
            # are exactly equal; on SQLite, NUMERIC is REAL, so evaluating
            # `gross - fees` in binary floating point can land one ulp away from
            # the stored `pnl_usd` and trip an equality test on a correct ledger.
            # One millionth of a dollar is far below any fee we charge.
            "abs(round(gross_pnl_usd - fees_usd, 6) - round(pnl_usd, 6)) <= 0.000001",
            name="pnl_is_net_of_fees",
        ),
        Index("ix_trades_symbol_entry", "symbol", "entry_time"),
        Index("ix_trades_strategy_exit", "strategy", "exit_time"),
    )


class Position(Base, TimestampMixin):
    """Open position, one row per symbol per mode."""

    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(QUANTITY, nullable=False)
    entry_price: Mapped[float] = mapped_column(PRICE, nullable=False)
    current_price: Mapped[float | None] = mapped_column(PRICE)
    stop_loss: Mapped[float | None] = mapped_column(PRICE)
    take_profit: Mapped[float | None] = mapped_column(PRICE)
    strategy: Mapped[str | None] = mapped_column(String(64))
    entry_fee_usd: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "mode", name="uq_positions_symbol_mode"),
        CheckConstraint("side IN ('buy','sell')", name="side_valid"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("entry_price > 0", name="entry_price_positive"),
    )


class Balance(Base, TimestampMixin):
    __tablename__ = "balances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    free: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)
    locked: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)

    __table_args__ = (
        UniqueConstraint("asset", "mode", name="uq_balances_asset_mode"),
        # A negative balance is how a double-spend hides. Refuse to store one.
        CheckConstraint("free >= 0", name="free_non_negative"),
        CheckConstraint("locked >= 0", name="locked_non_negative"),
    )


class PortfolioSnapshot(Base):
    """Equity time series. Append-only: the curve is the audit trail."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    equity_usd: Mapped[float] = mapped_column(USD, nullable=False)
    cash_usd: Mapped[float] = mapped_column(USD, nullable=False)
    positions_value_usd: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)
    unrealized_pnl_usd: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)
    realized_pnl_usd: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)
    daily_pnl_usd: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)
    total_exposure_usd: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)
    exposure_pct: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_drawdown_pct: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    peak_equity_usd: Mapped[float] = mapped_column(USD, default=0.0, nullable=False)
    positions: Mapped[list | None] = mapped_column(JSONType)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("equity_usd >= 0", name="equity_non_negative"),
        Index("ix_portfolio_mode_asof", "mode", "as_of"),
    )


class PaperPerformance(Base, TimestampMixin):
    """Forward-test evidence. Qualification reads this, not backtest results."""

    __tablename__ = "paper_performance"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    days_active: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    profit_factor: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    starting_balance: Mapped[float] = mapped_column(USD, default=10000.0, nullable=False)
    ending_balance: Mapped[float] = mapped_column(USD, default=10000.0, nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("strategy", name="uq_paper_strategy"),
        CheckConstraint("win_rate BETWEEN 0 AND 1", name="win_rate_range"),
    )


class Approval(Base):
    """Human sign-off for a live order. ``fingerprint`` pins the exact order."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str | None] = mapped_column(String(36))
    #: Hash of the order's material fields. Approving a changed order is a new
    #: approval, never a reuse of an old one.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired')", name="status_valid"
        ),
        Index("ix_approvals_status", "status"),
    )


class Volume24h(Base):
    """Rolling volume used by the liquidity filter.

    Kept in its own table so the filter reads one small row instead of scanning
    a day of tickers.
    """

    __tablename__ = "volume_24h"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    volume_usd: Mapped[float] = mapped_column(VOLUME, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (CheckConstraint("volume_usd >= 0", name="volume_non_negative"),)