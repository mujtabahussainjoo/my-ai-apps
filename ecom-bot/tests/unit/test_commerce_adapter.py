"""Unit tests for the commerce adapters and return-eligibility policy (TASK-023)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ecommerce_support.core.constants import RETURN_WINDOW_DAYS
from ecommerce_support.integrations import InMemoryCommerceAdapter, decide_return_eligibility
from ecommerce_support.schemas import (
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductSearchQuery,
    StockStatus,
)
from ecommerce_support.schemas.orders import Shipment


def _order(
    order_id: str,
    *,
    customer_id: str = "cust-1",
    status: OrderStatus = OrderStatus.DELIVERED,
    placed_at: datetime | None = None,
    shipment: Shipment | None = None,
) -> Order:
    return Order(
        id=order_id,
        customer_id=customer_id,
        status=status,
        total=Decimal("19.98"),
        placed_at=placed_at or datetime.now(UTC) - timedelta(days=2),
        items=[
            OrderItem(
                product_id="prd-1",
                name="Widget",
                quantity=1,
                unit_price=Decimal("19.98"),
                line_total=Decimal("19.98"),
            )
        ],
        shipment=shipment,
    )


def _product(product_id: str, *, name: str = "Widget", price: str = "9.99") -> Product:
    return Product(
        id=product_id,
        sku=f"SKU-{product_id}",
        name=name,
        category="tools",
        price=Decimal(price),
        stock_status=StockStatus.IN_STOCK,
        stock_quantity=5,
    )


class TestInMemoryAdapter:
    async def test_get_order_known_and_unknown(self) -> None:
        adapter = InMemoryCommerceAdapter(orders=[_order("ord-1")])
        assert (await adapter.get_order("ord-1")) is not None
        assert await adapter.get_order("nope") is None

    async def test_list_orders_scopes_and_paginates(self) -> None:
        now = datetime.now(UTC)
        adapter = InMemoryCommerceAdapter(
            orders=[
                _order("ord-1", customer_id="cust-1", placed_at=now - timedelta(days=1)),
                _order("ord-2", customer_id="cust-1", placed_at=now),
                _order("ord-3", customer_id="cust-2", placed_at=now),
            ]
        )
        page, total = await adapter.list_orders("cust-1", limit=1)
        assert total == 2
        assert [o.id for o in page] == ["ord-2"]

        page2, _ = await adapter.list_orders("cust-1", limit=1, offset=1)
        assert [o.id for o in page2] == ["ord-1"]

    async def test_track_shipment(self) -> None:
        shipment = Shipment(
            carrier="UPS",
            tracking_number="1Z999",
            status=OrderStatus.SHIPPED,
        )
        adapter = InMemoryCommerceAdapter(orders=[_order("ord-1", shipment=shipment)])
        assert (await adapter.track_shipment("ord-1")) is not None
        assert await adapter.track_shipment("nope") is None

    async def test_product_search_and_stock(self) -> None:
        adapter = InMemoryCommerceAdapter(
            products=[_product("prd-1", name="Hammer"), _product("prd-2", name="Drill")]
        )
        results, total = await adapter.search_products(ProductSearchQuery(query="drill"))
        assert total == 1
        assert results[0].id == "prd-2"
        assert (await adapter.get_product("prd-1")) is not None
        stock = await adapter.stock_info("prd-1")
        assert stock is not None and stock.status is StockStatus.IN_STOCK
        assert await adapter.stock_info("nope") is None


class TestReturnEligibilityPolicy:
    def test_delivered_within_window_is_eligible(self) -> None:
        now = datetime.now(UTC)
        order = _order("ord-1", placed_at=now - timedelta(days=5))
        result = decide_return_eligibility(order, now=now)
        assert result.eligible is True
        assert result.window_ends_at is not None

    def test_delivered_past_window_is_not_eligible(self) -> None:
        now = datetime.now(UTC)
        order = _order("ord-1", placed_at=now - timedelta(days=RETURN_WINDOW_DAYS + 1))
        result = decide_return_eligibility(order, now=now)
        assert result.eligible is False
        assert "closed" in result.reason

    def test_undelivered_is_not_eligible(self) -> None:
        order = _order("ord-1", status=OrderStatus.SHIPPED)
        result = decide_return_eligibility(order)
        assert result.eligible is False
        assert "delivered" in result.reason

    def test_naive_placed_at_is_treated_as_utc(self) -> None:
        order = _order("ord-1", placed_at=datetime(2026, 1, 1), status=OrderStatus.DELIVERED)
        result = decide_return_eligibility(order, now=datetime(2026, 1, 5, tzinfo=UTC))
        assert result.eligible is True
