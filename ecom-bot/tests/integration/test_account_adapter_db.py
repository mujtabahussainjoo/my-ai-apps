"""Integration test for the PostgreSQL fixture account adapter (TASK-026).

Skipped automatically when the compose database is unreachable; runs in a rolled-back txn.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.db.repositories import OrderRepository, ProductRepository, UserRepository
from ecommerce_support.integrations import SqlAccountAdapter
from ecommerce_support.schemas import Order, OrderItem, OrderStatus, Product, StockStatus


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
                stock_quantity=1,
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


async def test_sql_account_adapter_reads_profile_and_counts(session: AsyncSession) -> None:
    await _seed(session)
    adapter = SqlAccountAdapter(session)

    profile = await adapter.get_profile("cust-1")
    assert profile is not None
    assert profile.user_id == "cust-1"
    assert profile.email == "cust1@example.com"
    assert await adapter.order_count("cust-1") == 1
    assert await adapter.get_profile("missing") is None
