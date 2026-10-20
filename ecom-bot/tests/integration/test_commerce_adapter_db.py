"""Integration tests for the PostgreSQL fixture commerce adapter (TASK-023).

Run against the compose database with migrations applied (`make db-up && make migrate`);
skipped automatically when it is unreachable. Each test runs inside a rolled-back transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.agents import OrderWorker, ProductWorker
from ecommerce_support.db.repositories import OrderRepository, ProductRepository, UserRepository
from ecommerce_support.integrations import SqlCommerceAdapter
from ecommerce_support.schemas import (
    Order,
    OrderItem,
    OrderStatus,
    Product,
    StockStatus,
)
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName
from ecommerce_support.tools import create_order_registry, create_product_registry


async def _seed(session: AsyncSession) -> None:
    await UserRepository(session).upsert(
        user_id="cust-1", email="cust1@example.com", display_name="Cust One"
    )
    await ProductRepository(session).upsert_many(
        [
            Product(
                id="prd-1",
                sku="SKU-1",
                name="Widget",
                category="tools",
                price=Decimal("9.99"),
                stock_status=StockStatus.IN_STOCK,
                stock_quantity=3,
            )
        ]
    )
    await OrderRepository(session).upsert(
        Order(
            id="ord-1",
            customer_id="cust-1",
            status=OrderStatus.DELIVERED,
            total=Decimal("9.99"),
            placed_at=datetime(2026, 10, 1, tzinfo=UTC),
            items=[
                OrderItem(
                    product_id="prd-1",
                    name="Widget",
                    quantity=1,
                    unit_price=Decimal("9.99"),
                    line_total=Decimal("9.99"),
                )
            ],
        )
    )


async def test_sql_adapter_reads_order_and_products(session: AsyncSession) -> None:
    await _seed(session)
    adapter = SqlCommerceAdapter(session)

    order = await adapter.get_order("ord-1")
    assert order is not None and order.customer_id == "cust-1"

    product = await adapter.get_product("prd-1")
    assert product is not None and product.sku == "SKU-1"
    stock = await adapter.stock_info("prd-1")
    assert stock is not None and stock.quantity == 3

    summaries, total = await adapter.list_orders("cust-1")
    assert total == 1 and summaries[0].id == "ord-1"

    eligibility = await adapter.return_eligibility("ord-1")
    assert eligibility is not None and eligibility.eligible is True
    assert await adapter.get_order("missing") is None


async def test_order_worker_end_to_end_over_db(session: AsyncSession) -> None:
    await _seed(session)
    worker = OrderWorker(create_order_registry(SqlCommerceAdapter(session)))

    owned = await worker.get_order(
        "ord-1",
        context=ToolContext(agent=AgentName.ORDER, user_id="cust-1", conversation_id="conv-1"),
    )
    assert owned.answer.startswith("Order ord-1 is currently delivered")

    denied = await worker.get_order(
        "ord-1",
        context=ToolContext(agent=AgentName.ORDER, user_id="cust-2", conversation_id="conv-2"),
    )
    assert denied.answer == "I couldn't find that order on your account."


async def test_product_worker_end_to_end_over_db(session: AsyncSession) -> None:
    await _seed(session)
    worker = ProductWorker(create_product_registry(SqlCommerceAdapter(session)))

    response = await worker.search(
        query="Widget", context=ToolContext(agent=AgentName.PRODUCT, conversation_id="conv-1")
    )
    assert "Widget" in response.answer

    stock = await worker.check_stock(
        "prd-1", context=ToolContext(agent=AgentName.PRODUCT, conversation_id="conv-1")
    )
    assert "in_stock" in stock.answer
