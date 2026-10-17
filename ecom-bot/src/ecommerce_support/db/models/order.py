"""Order and order-item persistence (DATA-001 ``orders``, ``order_items``).

Shipment and address are stored as JSON to mirror the commerce-adapter contracts; the
repository translates them to typed schemas so ORM objects never leak outward.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import CreatedAtMixin, TimestampMixin, enum_column_type
from ecommerce_support.schemas.enums import OrderStatus


class Order(Base, TimestampMixin):
    """A customer order with a status, total, and optional address/shipment JSON."""

    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_customer_placed", "customer_id", "placed_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        enum_column_type(OrderStatus, "order_status"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shipping_address: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    shipment: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderItem.id",
        lazy="selectin",
    )


class OrderItem(Base, CreatedAtMixin):
    """A line item within an order."""

    __tablename__ = "order_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
