"""Order schemas: requests, orders, and the human-approval record."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from src.core.constants import MAX_ORDER_NOTIONAL_USD
from src.core.enums import ApprovalStatus, OrderSide, OrderType, TradingMode
from src.schemas.base import Base, PositiveFloat, Price, utcnow


class OrderRequest(Base):
    """A request to trade. Structurally incomplete requests are rejected early.

    Quantity and limit_price are mutually exclusive with notional_usd: exactly
    one sizing convention must be supplied so the risk engine never has to guess.
    """

    symbol: str = Field(min_length=3, max_length=32)
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: PositiveFloat | None = None
    notional_usd: PositiveFloat | None = None
    limit_price: Price | None = None
    stop_loss: Price | None = None
    take_profit: Price | None = None
    strategy: str | None = None
    signal_id: str | None = None
    leverage: float = Field(default=1.0, ge=1.0, le=5.0)
    mode: TradingMode = TradingMode.PAPER
    idempotency_key: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _check_sizing(self) -> OrderRequest:
        has_quantity = self.quantity is not None
        has_notional = self.notional_usd is not None
        if has_quantity == has_notional:
            raise ValueError("provide exactly one of quantity or notional_usd")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders must not carry limit_price")
        if self.notional_usd is not None and self.notional_usd > MAX_ORDER_NOTIONAL_USD:
            raise ValueError(f"notional_usd exceeds hard cap {MAX_ORDER_NOTIONAL_USD}")
        return self

    @property
    def sizing_basis(self) -> str:
        return "quantity" if self.quantity is not None else "notional"


class Order(Base):
    """An order in any venue. ``mode`` records which environment owns it."""

    id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: str
    quantity: PositiveFloat
    filled_quantity: float = Field(default=0.0, ge=0)
    price: Price | None = None
    average_price: Price | None = None
    fee_usd: float = Field(default=0.0, ge=0)
    stop_loss: Price | None = None
    take_profit: Price | None = None
    mode: TradingMode = TradingMode.PAPER
    strategy: str | None = None
    signal_id: str | None = None
    reject_reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def is_open(self) -> bool:
        return self.status in ("pending", "open", "partially_filled")

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)


class OrderFill(Base):
    order_id: str
    quantity: float = Field(gt=0)
    price: Price
    fee_usd: float = Field(default=0.0, ge=0)
    slippage_bps: float = 0.0
    filled_at: datetime = Field(default_factory=utcnow)


class ApprovalRequest(Base):
    """A proposal awaiting a human decision. Live orders cannot bypass this."""

    symbol: str
    side: OrderSide
    quantity: PositiveFloat
    limit_price: Price | None = None
    notional_usd: PositiveFloat | None = None
    strategy: str | None = None
    proposal_summary: str | None = None
    requester: str = "agent"


class Approval(Base):
    """Human sign-off. Bound to one exact order so it cannot be reused.

    ``fingerprint`` covers the economics; a mismatch at execution time
    invalidates the approval. ``expires_at`` keeps a sign-off from being
    replayed against a market that has since moved.
    """

    id: str
    fingerprint: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    order_id: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def is_valid(self) -> bool:
        if self.status is not ApprovalStatus.APPROVED:
            return False
        if self.expires_at is None:
            return False
        return utcnow() < self.expires_at