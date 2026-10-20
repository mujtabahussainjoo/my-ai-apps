"""In-memory commerce adapter for unit tests and framework-free agent runs (INT-003).

Deterministic, dependency-free mock: seed it with products and orders and it implements the full
:class:`CommerceAdapter` contract without a database. Integration tests exercise the PostgreSQL
fixture adapter (:class:`ecommerce_support.integrations.SqlCommerceAdapter`) instead.
"""

from __future__ import annotations

from collections.abc import Iterable

from ecommerce_support.integrations.commerce import CommerceAdapter
from ecommerce_support.integrations.sql_commerce import decide_return_eligibility
from ecommerce_support.schemas import (
    Order,
    OrderSummary,
    Product,
    ProductSearchQuery,
    ProductSummary,
    ReturnEligibility,
    Shipment,
    StockInfo,
)


class InMemoryCommerceAdapter(CommerceAdapter):
    """Mock adapter holding products and orders in memory."""

    def __init__(
        self,
        *,
        products: Iterable[Product] = (),
        orders: Iterable[Order] = (),
    ) -> None:
        self._products: dict[str, Product] = {p.id: p for p in products}
        self._orders: dict[str, Order] = {o.id: o for o in orders}

    def add_product(self, product: Product) -> None:
        self._products[product.id] = product

    def add_order(self, order: Order) -> None:
        self._orders[order.id] = order

    async def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    async def list_orders(
        self, customer_id: str, *, limit: int = 10, offset: int = 0
    ) -> tuple[list[OrderSummary], int]:
        owned = [o for o in self._orders.values() if o.customer_id == customer_id]
        owned.sort(key=lambda o: o.placed_at, reverse=True)
        page = owned[offset : offset + limit]
        summaries = [
            OrderSummary(
                id=o.id,
                status=o.status,
                currency=o.currency,
                total=o.total,
                placed_at=o.placed_at,
                item_count=len(o.items),
            )
            for o in page
        ]
        return summaries, len(owned)

    async def track_shipment(self, order_id: str) -> Shipment | None:
        order = self._orders.get(order_id)
        return order.shipment if order is not None else None

    async def return_eligibility(self, order_id: str) -> ReturnEligibility | None:
        order = self._orders.get(order_id)
        if order is None:
            return None
        return decide_return_eligibility(order)

    async def search_products(self, query: ProductSearchQuery) -> tuple[list[ProductSummary], int]:
        matches = [
            p
            for p in self._products.values()
            if (query.category is None or p.category == query.category)
            and (query.min_price is None or p.price >= query.min_price)
            and (query.max_price is None or p.price <= query.max_price)
            and (
                query.query is None
                or query.query.lower() in p.name.lower()
                or query.query.lower() in p.sku.lower()
            )
        ]
        matches.sort(key=lambda p: p.name)
        total = len(matches)
        page = matches[query.offset : query.offset + query.limit]
        summaries = [
            ProductSummary(
                id=p.id,
                sku=p.sku,
                name=p.name,
                category=p.category,
                price=p.price,
                currency=p.currency,
                stock_status=p.stock_status,
            )
            for p in page
        ]
        return summaries, total

    async def get_product(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    async def stock_info(self, product_id: str) -> StockInfo | None:
        product = self._products.get(product_id)
        if product is None:
            return None
        return StockInfo(
            product_id=product.id,
            status=product.stock_status,
            quantity=product.stock_quantity,
        )
