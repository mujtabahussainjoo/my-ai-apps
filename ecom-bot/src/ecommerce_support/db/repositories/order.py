"""Order repository (ownership-scoped reads; commerce adapter fixtures)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import Order as OrderRow
from ecommerce_support.db.models import OrderItem as OrderItemRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import Address, Order, OrderItem, OrderSummary, Shipment


def _to_order(row: OrderRow) -> Order:
    return Order(
        id=row.id,
        customer_id=row.customer_id,
        status=row.status,
        currency=row.currency,
        total=row.total,
        placed_at=row.placed_at,
        updated_at=row.updated_at,
        shipping_address=(
            Address.model_validate(row.shipping_address) if row.shipping_address else None
        ),
        shipment=Shipment.model_validate(row.shipment) if row.shipment else None,
        items=[
            OrderItem(
                product_id=item.product_id,
                name=item.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item in row.items
        ],
    )


class OrderRepository(BaseRepository):
    """Persistence for orders and their items (FR-020, DATA-004 seed fixtures)."""

    async def get(self, order_id: str) -> Order | None:
        row = await self.session.scalar(
            select(OrderRow).where(OrderRow.id == order_id).options(selectinload(OrderRow.items))
        )
        return _to_order(row) if row is not None else None

    async def list_for_customer(
        self, customer_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[OrderSummary], int]:
        condition = OrderRow.customer_id == customer_id
        total = await self.session.scalar(
            select(func.count()).select_from(OrderRow).where(condition)
        )
        stmt = (
            select(OrderRow)
            .where(condition)
            .options(selectinload(OrderRow.items))
            .order_by(OrderRow.placed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self.session.scalars(stmt)).all())
        summaries = [
            OrderSummary(
                id=row.id,
                status=row.status,
                currency=row.currency,
                total=row.total,
                placed_at=row.placed_at,
                item_count=len(row.items),
            )
            for row in rows
        ]
        return summaries, int(total or 0)

    async def upsert(self, order: Order) -> Order:
        """Insert or fully replace an order and its items (idempotent by order id)."""
        row = await self.session.scalar(
            select(OrderRow).where(OrderRow.id == order.id).options(selectinload(OrderRow.items))
        )
        if row is None:
            row = OrderRow(id=order.id)
            self.session.add(row)
        else:
            row.items.clear()
            await self.session.flush()
        row.customer_id = order.customer_id
        row.status = order.status
        row.currency = order.currency
        row.total = order.total
        row.placed_at = order.placed_at
        row.shipping_address = (
            order.shipping_address.model_dump(mode="json") if order.shipping_address else None
        )
        row.shipment = order.shipment.model_dump(mode="json") if order.shipment else None

        for item in order.items:
            row.items.append(
                OrderItemRow(
                    id=new_id("oitm"),
                    order_id=order.id,
                    product_id=item.product_id,
                    name=item.name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    line_total=item.line_total,
                )
            )
        await self.session.flush()
        return _to_order(row)
