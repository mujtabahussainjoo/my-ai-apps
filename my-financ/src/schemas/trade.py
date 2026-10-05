"""Trade schemas. Trades are the unit of performance measurement."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from src.core.enums import OrderSide, TradingMode
from src.schemas.base import Base, PositiveFloat, Price, utcnow

ExitReason = Literal[
    "take_profit", "stop_loss", "manual", "signal_flip", "end_of_data", "liquidation_guard"
]


class Trade(Base):
    """A closed round-trip.

    ``risk_multiple`` expresses P&L in units of the risk taken at entry
    (R-multiple). It is the most useful single number for comparing strategies
    because it is independent of position size.
    """

    id: str
    order_id: str
    symbol: str
    side: OrderSide
    strategy: str | None = None
    quantity: PositiveFloat
    entry_price: Price
    exit_price: Price | None = None
    entry_time: datetime = Field(default_factory=utcnow)
    exit_time: datetime | None = None
    gross_pnl_usd: float = 0.0
    fees_usd: float = Field(default=0.0, ge=0)
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    initial_risk_per_unit: float | None = None
    risk_multiple: float | None = None
    #: The *planned* reward-to-risk of the originating signal (target vs stop).
    #: Distinct from ``risk_multiple``, which is what actually happened.
    planned_risk_reward: float | None = None
    exit_reason: ExitReason | None = None
    mode: TradingMode = TradingMode.PAPER
    notes: str | None = None

    @property
    def is_winner(self) -> bool:
        return self.pnl_usd > 0

    @property
    def duration_seconds(self) -> float | None:
        if self.exit_time is None:
            return None
        return (self.exit_time - self.entry_time).total_seconds()


class ClosedTradeResult(Base):
    trade_id: str
    pnl_usd: float
    pnl_pct: float
    risk_multiple: float | None
    exit_reason: ExitReason | None
    duration_seconds: float | None