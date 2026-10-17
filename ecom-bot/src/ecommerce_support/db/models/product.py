"""Product catalog persistence (DATA-001 ``products``)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import TimestampMixin, enum_column_type
from ecommerce_support.schemas.enums import StockStatus


class Product(Base, TimestampMixin):
    """A catalog product. In production the commerce adapter is source of truth (DATA-004)."""

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    stock_status: Mapped[StockStatus] = mapped_column(
        enum_column_type(StockStatus, "stock_status"), nullable=False
    )
    stock_quantity: Mapped[int | None] = mapped_column(nullable=True)
    attributes: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
