"""Market data tables.

Candles are the bulk of the data volume and the only table here that is written
in a tight loop, so it is the one with a composite uniqueness constraint and a
range-friendly index. Duplicated candles would silently corrupt every indicator
computed downstream, so the constraint is load-bearing rather than cosmetic.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import (
    BIGINT_PK,
    PRICE,
    QUANTITY,
    VOLUME,
    Base,
    TimestampMixin,
    new_id,
)


class Candle(Base, TimestampMixin):
    __tablename__ = "candles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    open: Mapped[float] = mapped_column(PRICE, nullable=False)
    high: Mapped[float] = mapped_column(PRICE, nullable=False)
    low: Mapped[float] = mapped_column(PRICE, nullable=False)
    close: Mapped[float] = mapped_column(PRICE, nullable=False)
    volume: Mapped[float] = mapped_column(VOLUME, nullable=False)

    # A malformed candle is worse than a missing one: indicators would treat
    # high < low as a real range and produce confident nonsense.
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candles_symbol_timeframe_timestamp"),
        CheckConstraint("high >= low", name="high_ge_low"),
        CheckConstraint("high >= open AND high >= close", name="high_is_max"),
        CheckConstraint("low <= open AND low <= close", name="low_is_min"),
        CheckConstraint("open > 0 AND close > 0", name="prices_positive"),
        CheckConstraint("volume >= 0", name="volume_non_negative"),
        Index("ix_candles_symbol_tf_ts", "symbol", "timeframe", "timestamp"),
        Index("ix_candles_ts", "timestamp"),
    )


class TickerSnapshot(Base):
    """Point-in-time prices, kept for audit.

    Every risk decision references the price it was made against, so that the
    decision can be reconstructed months later.
    """

    __tablename__ = "ticker_snapshots"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    last: Mapped[float] = mapped_column(PRICE, nullable=False)
    bid: Mapped[float | None] = mapped_column(PRICE)
    ask: Mapped[float | None] = mapped_column(PRICE)
    volume_24h: Mapped[float | None] = mapped_column(VOLUME)
    source: Mapped[str] = mapped_column(String(32), default="binance", nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_ticker_symbol_ts", "symbol", "timestamp"),
    )


class Symbol(Base, TimestampMixin):
    """Reference data, so the UI can list tradable pairs without hardcoding them."""

    __tablename__ = "symbols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    base_asset: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(16), default="USDT", nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    min_order_size: Mapped[float | None] = mapped_column(QUANTITY)
    price_precision: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    quantity_precision: Mapped[int] = mapped_column(Integer, default=8, nullable=False)

    __table_args__ = (CheckConstraint("price_precision BETWEEN 0 AND 18", name="price_precision_range"),)