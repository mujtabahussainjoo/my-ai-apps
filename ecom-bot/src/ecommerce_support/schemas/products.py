"""Product catalog contracts (commerce adapter output; FR-021)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, model_validator

from ecommerce_support.schemas.common import CURRENCY_PATTERN, Schema
from ecommerce_support.schemas.enums import StockStatus


class Product(Schema):
    """A catalog product. Prices/stock come from the adapter, never invented."""

    id: str = Field(min_length=1)
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", pattern=CURRENCY_PATTERN)
    stock_status: StockStatus
    stock_quantity: int | None = Field(default=None, ge=0)
    attributes: dict[str, str] = Field(default_factory=dict)


class ProductSummary(Schema):
    """Lightweight product projection for search results."""

    id: str = Field(min_length=1)
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", pattern=CURRENCY_PATTERN)
    stock_status: StockStatus


class ProductSearchQuery(Schema):
    """Catalog search parameters with a validated price range."""

    query: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    min_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    max_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check_price_range(self) -> ProductSearchQuery:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must be less than or equal to max_price")
        return self


class StockInfo(Schema):
    """Stock check result for a single product (FR-039)."""

    product_id: str = Field(min_length=1)
    status: StockStatus
    quantity: int | None = Field(default=None, ge=0)
    restock_eta: datetime | None = None
