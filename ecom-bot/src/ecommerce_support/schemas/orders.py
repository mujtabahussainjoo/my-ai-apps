"""Order, shipment, and return-eligibility contracts (commerce adapter output)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from ecommerce_support.schemas.common import CURRENCY_PATTERN, Schema
from ecommerce_support.schemas.enums import OrderStatus

Money = Decimal


class Address(Schema):
    """A shipping/billing address (PII — redact in logs/tickets)."""

    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    region: str | None = Field(default=None, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    country: str = Field(min_length=2, max_length=2)


class OrderItem(Schema):
    """A single line item within an order."""

    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(ge=1)
    unit_price: Money = Field(ge=0, max_digits=12, decimal_places=2)
    line_total: Money = Field(ge=0, max_digits=12, decimal_places=2)


class ShipmentEvent(Schema):
    """A timestamped tracking event."""

    status: OrderStatus
    description: str = ""
    occurred_at: datetime


class Shipment(Schema):
    """Shipment/tracking information for an order (FR-020)."""

    carrier: str = Field(min_length=1, max_length=100)
    tracking_number: str = Field(min_length=1, max_length=100)
    tracking_url: str | None = None
    status: OrderStatus
    estimated_delivery: datetime | None = None
    events: list[ShipmentEvent] = Field(default_factory=list)


class Order(Schema):
    """A customer order with items and optional shipment (FR-020)."""

    id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    status: OrderStatus
    currency: str = Field(default="USD", pattern=CURRENCY_PATTERN)
    items: list[OrderItem] = Field(default_factory=list)
    total: Money = Field(ge=0, max_digits=12, decimal_places=2)
    placed_at: datetime
    updated_at: datetime | None = None
    shipping_address: Address | None = None
    shipment: Shipment | None = None


class OrderSummary(Schema):
    """Lightweight order projection for lists."""

    id: str = Field(min_length=1)
    status: OrderStatus
    currency: str = Field(default="USD", pattern=CURRENCY_PATTERN)
    total: Money = Field(ge=0, max_digits=12, decimal_places=2)
    placed_at: datetime
    item_count: int = Field(ge=0)


class ReturnEligibility(Schema):
    """Return-eligibility decision for an order (FR-039)."""

    order_id: str = Field(min_length=1)
    eligible: bool
    reason: str = ""
    window_ends_at: datetime | None = None
