"""Seed deterministic mock commerce data (users, products, orders) — TASK-011.

These are **test/demo fixtures only**; the production source of truth for orders and products
is the commerce adapter (`requirement.md` DATA-004). IDs and values are fixed so runs are
deterministic, and every write goes through repository ``upsert`` calls so re-running the
script is idempotent.

Usage::

    make seed
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.db.repositories import (
    OrderRepository,
    ProductRepository,
    UserRepository,
)
from ecommerce_support.db.session import close_engine, session_scope
from ecommerce_support.schemas import (
    Address,
    Order,
    OrderItem,
    Product,
    Shipment,
    ShipmentEvent,
)
from ecommerce_support.schemas.enums import OrderStatus, StockStatus


@dataclass(frozen=True)
class SeedUser:
    user_id: str
    email: str
    display_name: str


@dataclass(frozen=True)
class SeedResult:
    """Row counts written by a seed run (stable across repeated runs)."""

    users: int
    products: int
    orders: int


USERS: tuple[SeedUser, ...] = (
    SeedUser("usr-alice", "alice@example.com", "Alice Nguyen"),
    SeedUser("usr-bob", "bob@example.com", "Bob Carter"),
)

PRODUCTS: tuple[Product, ...] = (
    Product(
        id="prd-lamp-01",
        sku="LAMP-100",
        name="Aurora Desk Lamp",
        description="Dimmable LED desk lamp with wireless charging base.",
        category="lighting",
        price=Decimal("39.99"),
        stock_status=StockStatus.IN_STOCK,
        stock_quantity=25,
        attributes={"color": "white", "power": "12W"},
    ),
    Product(
        id="prd-chair-01",
        sku="CHAIR-200",
        name="Ergo Task Chair",
        description="Mesh-back task chair with adjustable lumbar support.",
        category="office",
        price=Decimal("189.00"),
        stock_status=StockStatus.LOW_STOCK,
        stock_quantity=3,
        attributes={"color": "black"},
    ),
    Product(
        id="prd-kettle-01",
        sku="KETTLE-300",
        name="Rapid Electric Kettle",
        description="1.7L stainless steel kettle, boils in under 3 minutes.",
        category="kitchen",
        price=Decimal("29.50"),
        stock_status=StockStatus.IN_STOCK,
        stock_quantity=40,
        attributes={"capacity": "1.7L"},
    ),
    Product(
        id="prd-head-01",
        sku="HEAD-400",
        name="Pulse Wireless Headphones",
        description="Over-ear active noise-cancelling headphones, 30h battery.",
        category="audio",
        price=Decimal("99.99"),
        stock_status=StockStatus.IN_STOCK,
        stock_quantity=15,
        attributes={"battery": "30h"},
    ),
    Product(
        id="prd-mat-01",
        sku="MAT-500",
        name="Eco Yoga Mat",
        description="Non-slip natural rubber yoga mat, 6mm.",
        category="fitness",
        price=Decimal("24.00"),
        stock_status=StockStatus.OUT_OF_STOCK,
        stock_quantity=0,
        attributes={"thickness": "6mm"},
    ),
    Product(
        id="prd-bottle-01",
        sku="BOTTLE-600",
        name="Insulated Water Bottle",
        description="750ml vacuum-insulated bottle, keeps drinks cold 24h.",
        category="outdoor",
        price=Decimal("19.99"),
        stock_status=StockStatus.IN_STOCK,
        stock_quantity=60,
        attributes={"capacity": "750ml"},
    ),
    Product(
        id="prd-speaker-01",
        sku="SPKR-700",
        name="Nimbus Bluetooth Speaker",
        description="Portable waterproof Bluetooth speaker.",
        category="audio",
        price=Decimal("59.00"),
        stock_status=StockStatus.BACKORDER,
        stock_quantity=0,
        attributes={"waterproof": "IPX7"},
    ),
    Product(
        id="prd-desk-01",
        sku="DESK-800",
        name="Bamboo Standing Desk",
        description="Electric height-adjustable standing desk, 120x60cm.",
        category="office",
        price=Decimal("349.00"),
        stock_status=StockStatus.IN_STOCK,
        stock_quantity=7,
        attributes={"width": "120cm"},
    ),
)

ALICE_ADDRESS = Address(
    line1="12 Maple Street",
    city="Springfield",
    region="IL",
    postal_code="62704",
    country="US",
)

BOB_ADDRESS = Address(
    line1="88 Oak Avenue",
    line2="Apt 4B",
    city="Portland",
    region="OR",
    postal_code="97201",
    country="US",
)

ORDERS: tuple[Order, ...] = (
    Order(
        id="ord-alice-1",
        customer_id="usr-alice",
        status=OrderStatus.DELIVERED,
        total=Decimal("69.49"),
        placed_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        shipping_address=ALICE_ADDRESS,
        shipment=Shipment(
            carrier="FastShip",
            tracking_number="FS-10001",
            tracking_url="https://example.com/track/FS-10001",
            status=OrderStatus.DELIVERED,
            estimated_delivery=datetime(2026, 1, 8, 17, 0, tzinfo=UTC),
            events=[
                ShipmentEvent(
                    status=OrderStatus.SHIPPED,
                    description="Picked up",
                    occurred_at=datetime(2026, 1, 6, 9, 0, tzinfo=UTC),
                ),
                ShipmentEvent(
                    status=OrderStatus.DELIVERED,
                    description="Delivered to front door",
                    occurred_at=datetime(2026, 1, 8, 15, 30, tzinfo=UTC),
                ),
            ],
        ),
        items=[
            OrderItem(
                product_id="prd-lamp-01",
                name="Aurora Desk Lamp",
                quantity=1,
                unit_price=Decimal("39.99"),
                line_total=Decimal("39.99"),
            ),
            OrderItem(
                product_id="prd-kettle-01",
                name="Rapid Electric Kettle",
                quantity=1,
                unit_price=Decimal("29.50"),
                line_total=Decimal("29.50"),
            ),
        ],
    ),
    Order(
        id="ord-alice-2",
        customer_id="usr-alice",
        status=OrderStatus.SHIPPED,
        total=Decimal("189.00"),
        placed_at=datetime(2026, 2, 10, 14, 30, tzinfo=UTC),
        shipping_address=ALICE_ADDRESS,
        shipment=Shipment(
            carrier="FastShip",
            tracking_number="FS-10002",
            status=OrderStatus.IN_TRANSIT,
            estimated_delivery=datetime(2026, 2, 14, 17, 0, tzinfo=UTC),
        ),
        items=[
            OrderItem(
                product_id="prd-chair-01",
                name="Ergo Task Chair",
                quantity=1,
                unit_price=Decimal("189.00"),
                line_total=Decimal("189.00"),
            )
        ],
    ),
    Order(
        id="ord-bob-1",
        customer_id="usr-bob",
        status=OrderStatus.PROCESSING,
        total=Decimal("219.97"),
        placed_at=datetime(2026, 3, 1, 8, 15, tzinfo=UTC),
        shipping_address=BOB_ADDRESS,
        items=[
            OrderItem(
                product_id="prd-head-01",
                name="Pulse Wireless Headphones",
                quantity=2,
                unit_price=Decimal("99.99"),
                line_total=Decimal("199.98"),
            ),
            OrderItem(
                product_id="prd-bottle-01",
                name="Insulated Water Bottle",
                quantity=1,
                unit_price=Decimal("19.99"),
                line_total=Decimal("19.99"),
            ),
        ],
    ),
)


async def seed_demo_data(session: AsyncSession) -> SeedResult:
    """Upsert the demo fixtures into ``session`` (caller owns the transaction).

    Idempotent: every entity is written by primary key, and orders are fully replaced, so
    repeated runs converge to the same rows without duplicates.
    """
    user_repo = UserRepository(session)
    for user in USERS:
        await user_repo.upsert(
            user_id=user.user_id, email=user.email, display_name=user.display_name
        )

    product_repo = ProductRepository(session)
    await product_repo.upsert_many(PRODUCTS)

    order_repo = OrderRepository(session)
    for order in ORDERS:
        await order_repo.upsert(order)

    return SeedResult(users=len(USERS), products=len(PRODUCTS), orders=len(ORDERS))


async def main() -> None:
    """CLI entry point: seed within a transaction and report counts."""
    async with session_scope() as session:
        result = await seed_demo_data(session)
    print(f"Seeded {result.users} users, {result.products} products, {result.orders} orders.")
    await close_engine()


if __name__ == "__main__":
    asyncio.run(main())
