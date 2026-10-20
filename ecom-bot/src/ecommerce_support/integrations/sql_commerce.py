"""Mock/fixture commerce adapter backed by PostgreSQL seed data (INT-003, DATA-004).

v1 serves demo data from the ``orders``/``orders_items``/``products`` tables so CI and local runs
need no external commerce backend. It implements the full :class:`CommerceAdapter` contract, so a
real Magento/Adobe Commerce adapter can replace it without touching agents or tools
(see ``docs/commerce-adapter.md``).

Return-eligibility is computed here (from order state + delivery date) because it is a commerce
concern; the 30-day window is declared in :data:`ecommerce_support.core.constants.RETURN_WINDOW_DAYS`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.constants import RETURN_WINDOW_DAYS
from ecommerce_support.db.repositories.order import OrderRepository
from ecommerce_support.db.repositories.product import ProductRepository
from ecommerce_support.integrations.commerce import CommerceAdapter
from ecommerce_support.schemas import (
    Order,
    OrderStatus,
    OrderSummary,
    Product,
    ProductSearchQuery,
    ProductSummary,
    ReturnEligibility,
    Shipment,
    StockInfo,
)


class SqlCommerceAdapter(CommerceAdapter):
    """Fixture commerce adapter reading the seeded PostgreSQL catalog and orders.

    Mock/fixture-only: the production source of truth is a real commerce adapter.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_order(self, order_id: str) -> Order | None:
        return await OrderRepository(self._session).get(order_id)

    async def list_orders(
        self, customer_id: str, *, limit: int = 10, offset: int = 0
    ) -> tuple[list[OrderSummary], int]:
        return await OrderRepository(self._session).list_for_customer(
            customer_id, limit=limit, offset=offset
        )

    async def track_shipment(self, order_id: str) -> Shipment | None:
        order = await self.get_order(order_id)
        return order.shipment if order is not None else None

    async def return_eligibility(self, order_id: str) -> ReturnEligibility | None:
        order = await self.get_order(order_id)
        if order is None:
            return None
        return decide_return_eligibility(order)

    async def search_products(self, query: ProductSearchQuery) -> tuple[list[ProductSummary], int]:
        return await ProductRepository(self._session).search(query)

    async def get_product(self, product_id: str) -> Product | None:
        return await ProductRepository(self._session).get(product_id)

    async def stock_info(self, product_id: str) -> StockInfo | None:
        return await ProductRepository(self._session).stock_info(product_id)


def decide_return_eligibility(order: Order, *, now: datetime | None = None) -> ReturnEligibility:
    """Compute return eligibility from order state and delivery date (FR-039).

    Only delivered orders are eligible, and only within :data:`RETURN_WINDOW_DAYS` of placement.
    """
    reference = now or datetime.now(UTC)
    placed_at = order.placed_at
    if placed_at.tzinfo is None:
        placed_at = placed_at.replace(tzinfo=UTC)
    window_ends_at = placed_at + timedelta(days=RETURN_WINDOW_DAYS)

    if order.status is not OrderStatus.DELIVERED:
        return ReturnEligibility(
            order_id=order.id,
            eligible=False,
            reason="Returns are available once the order has been delivered.",
            window_ends_at=window_ends_at,
        )
    if reference > window_ends_at:
        return ReturnEligibility(
            order_id=order.id,
            eligible=False,
            reason=f"The {RETURN_WINDOW_DAYS}-day return window has closed.",
            window_ends_at=window_ends_at,
        )
    return ReturnEligibility(
        order_id=order.id,
        eligible=True,
        reason=f"Eligible for return within {RETURN_WINDOW_DAYS} days of delivery.",
        window_ends_at=window_ends_at,
    )
