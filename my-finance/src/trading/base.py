"""Execution contracts shared by every broker adapter.

The design rule that matters: **nothing in this package decides whether an order
is allowed to trade.** That judgement belongs to the hard risk engine and arrives
as a :class:`RiskAssessment`. An adapter receives an already-authorised,
already-sized instruction and is only responsible for the mechanics of filling it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import Field

from src.core.enums import TradingMode
from src.core.exceptions import ExecutionError
from src.schemas.base import Base
from src.schemas.market import Ticker
from src.schemas.order import Order, OrderRequest, OrderType


@dataclass(frozen=True, slots=True)
class ExecutionInstruction:
    """An order that has already passed the risk gate.

    The quantities here come from :attr:`RiskAssessment.approved_quantity` and
    :attr:`RiskAssessment.approved_notional_usd` — never from the caller's
    original request. So even if a caller re-derives a bigger size, the
    instruction is already clamped.
    """

    request: OrderRequest
    quantity: float
    mode: TradingMode
    stop_loss: float | None = None
    take_profit: float | None = None
    leverage: float = 1.0
    assessment_id: str | None = None
    approval_id: str | None = None
    #: Why this order is being placed. Carried through to the ledger so a
    #: stop-loss exit is not filed as a signal reversal, which would corrupt
    #: every downstream exit-reason statistic.
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ExecutionError(f"refusing to build an instruction with quantity {self.quantity}")


class FillReport(Base):
    """What actually happened at the venue."""

    order_id: str
    client_order_id: str
    symbol: str
    side: str
    status: str
    requested_quantity: float = Field(ge=0)
    filled_quantity: float = Field(default=0.0, ge=0)
    average_price: float | None = None
    fee_usd: float = Field(default=0.0, ge=0)
    slippage_bps: float = 0.0
    fills: list[dict] = Field(default_factory=list)
    filled_at: datetime | None = None
    order: Order | None = None

    @property
    def is_filled(self) -> bool:
        return self.status in ("filled", "closed") and self.filled_quantity > 0

    @property
    def is_open(self) -> bool:
        return self.status in ("pending", "open", "partially_filled")

    @property
    def unfilled_quantity(self) -> float:
        return max(0.0, self.requested_quantity - self.filled_quantity)

    @property
    def partial(self) -> bool:
        return 0 < self.filled_quantity < self.requested_quantity


@dataclass(slots=True)
class PositionExit:
    """A decision to close an open position."""

    symbol: str
    price: float
    quantity: float
    reason: str
    mode: TradingMode
    trade_id: str | None = None
    realized_pnl_usd: float = 0.0
    fees_usd: float = 0.0
    details: dict = field(default_factory=dict)


class Broker(ABC):
    """A venue that can accept authorised instructions.

    Implementations must be idempotent on ``client_order_id``: submitting the
    same id twice returns the original order rather than placing a second one.
    """

    mode: TradingMode

    @abstractmethod
    def submit(self, instruction: ExecutionInstruction, ticker: Ticker) -> FillReport:
        """Place or rest an authorised order."""

    @abstractmethod
    def cancel(self, client_order_id: str) -> bool:
        """Cancel a resting order. True if something was cancelled."""

    @abstractmethod
    def fetch_balances(self) -> dict[str, float]:
        """Current free balance per asset."""

    def poll_open_orders(self) -> list[Order]:
        return []

    def __enter__(self) -> Broker:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def fill_price_for(
    ticker: Ticker,
    side: str,
    *,
    slippage_rate: float,
    limit_price: float | None = None,
    order_type: OrderType = OrderType.MARKET,
) -> float | None:
    """Price a fill would occur at, or ``None`` if the order should not fill.

    Market orders cross the spread: a buy lifts the ask, a sell hits the bid.
    Limit orders only fill when the market has reached the limit, and they fill
    at the limit rather than at a worse price.
    """
    buy = side == "buy"
    marketable_price = ticker.ask if buy else ticker.bid
    reference = marketable_price or ticker.last

    if is_limit(order_type) and limit_price is not None:
        # A buy limit fills only if the ask is at or below the limit; the seller
        # limit fills only if the bid is at or above it. Otherwise it rests.
        if buy and reference > limit_price:
            return None
        if not buy and reference < limit_price:
            return None
        return float(limit_price)

    slipped = reference * (1 + slippage_rate) if buy else reference * (1 - slippage_rate)
    return round(max(slipped, 1e-12), 8)


def side_value(side: object) -> str:
    """Normalise a side to its string form.

    ORM rows store ``side`` as a plain string while the schemas use an enum, so
    anything crossing that boundary has to tolerate both.
    """
    return str(getattr(side, "value", side))


def is_limit(order_type: object) -> bool:
    """True for limit orders, tolerating the enum or its stored string form.

    ORM rows persist ``order_type`` as text while the schemas use an enum, so an
    identity comparison against ``OrderType.LIMIT`` silently fails on rows read
    back from the database.
    """
    return str(getattr(order_type, "value", order_type)) == OrderType.LIMIT.value


def fee_for(notional: float, taker_fee_rate: float) -> float:
    """Taker fee in USD for a filled notional."""
    return round(abs(notional) * taker_fee_rate, 8)


__all__ = [
    "Broker",
    "ExecutionError",
    "ExecutionInstruction",
    "FillReport",
    "PositionExit",
    "fee_for",
    "fill_price_for",
    "is_limit",
    "side_value",
]
