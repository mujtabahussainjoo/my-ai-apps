"""Integration tests for the demo seeding script (TASK-011).

Uses the rollback ``session`` fixture from ``tests/integration/conftest.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.db.models import Order as OrderRow
from ecommerce_support.db.models import OrderItem as OrderItemRow
from ecommerce_support.db.models import Product as ProductRow
from ecommerce_support.db.models import User as UserRow
from ecommerce_support.schemas.enums import OrderStatus
from scripts.seed_demo_data import SeedResult, seed_demo_data

pytestmark = pytest.mark.integration


async def _counts(session: AsyncSession) -> dict[str, int]:
    return {
        "users": int(await session.scalar(select(func.count()).select_from(UserRow)) or 0),
        "products": int(await session.scalar(select(func.count()).select_from(ProductRow)) or 0),
        "orders": int(await session.scalar(select(func.count()).select_from(OrderRow)) or 0),
        "order_items": int(
            await session.scalar(select(func.count()).select_from(OrderItemRow)) or 0
        ),
    }


async def test_seed_populates_expected_rows(session: AsyncSession) -> None:
    result = await seed_demo_data(session)
    assert result == SeedResult(users=2, products=8, orders=3)

    counts = await _counts(session)
    assert counts == {"users": 2, "products": 8, "orders": 3, "order_items": 5}

    order = await session.get(OrderRow, "ord-alice-1")
    assert order is not None
    assert order.status == OrderStatus.DELIVERED
    assert len(order.items) == 2


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    first = await seed_demo_data(session)
    counts_after_first = await _counts(session)

    second = await seed_demo_data(session)
    counts_after_second = await _counts(session)

    assert first == second
    assert (
        counts_after_first
        == counts_after_second
        == {
            "users": 2,
            "products": 8,
            "orders": 3,
            "order_items": 5,
        }
    )


async def test_seed_updates_existing_rows(session: AsyncSession) -> None:
    await seed_demo_data(session)

    user = await session.get(UserRow, "usr-alice")
    assert user is not None
    user.display_name = "Temporary Name"
    await session.flush()

    await seed_demo_data(session)
    refreshed = await session.get(UserRow, "usr-alice")
    assert refreshed is not None
    assert refreshed.display_name == "Alice Nguyen"
