"""Unit tests for the order worker's deterministic, data-faithful responses (TASK-023)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ecommerce_support.agents import OrderWorker
from ecommerce_support.integrations import InMemoryCommerceAdapter
from ecommerce_support.schemas import Order, OrderItem, OrderStatus
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools import create_order_registry


def _order(order_id: str, *, customer_id: str = "cust-1") -> Order:
    return Order(
        id=order_id,
        customer_id=customer_id,
        status=OrderStatus.DELIVERED,
        currency="USD",
        total=Decimal("19.98"),
        placed_at=datetime(2026, 10, 1, tzinfo=UTC),
        items=[
            OrderItem(
                product_id="prd-1",
                name="Widget",
                quantity=2,
                unit_price=Decimal("9.99"),
                line_total=Decimal("19.98"),
            )
        ],
    )


@pytest.fixture
def worker() -> OrderWorker:
    adapter = InMemoryCommerceAdapter(
        orders=[_order("ord-1"), _order("ord-2", customer_id="cust-9")]
    )
    return OrderWorker(create_order_registry(adapter))


def _ctx() -> ToolContext:
    return ToolContext(agent=AgentName.ORDER, user_id="cust-1", conversation_id="conv-1")


class TestOrderWorker:
    async def test_get_order_answers_with_data(self, worker: OrderWorker) -> None:
        response = await worker.get_order("ord-1", context=_ctx())
        assert response.agent is AgentName.ORDER
        assert "ord-1" in response.answer
        assert "delivered" in response.answer
        assert response.tool_executions[0].status is ToolCallStatus.OK

    async def test_get_order_not_owned_is_polite(self, worker: OrderWorker) -> None:
        response = await worker.get_order("ord-2", context=_ctx())
        assert response.answer == "I couldn't find that order on your account."
        assert response.tool_executions[0].status is ToolCallStatus.ERROR

    async def test_track_untracked_order(self, worker: OrderWorker) -> None:
        response = await worker.track_shipment("ord-1", context=_ctx())
        assert "no shipment tracking yet" in response.answer

    async def test_return_eligibility(self, worker: OrderWorker) -> None:
        response = await worker.return_eligibility("ord-1", context=_ctx())
        assert "eligible for return" in response.answer

    async def test_list_orders(self, worker: OrderWorker) -> None:
        response = await worker.list_orders(context=_ctx())
        assert "ord-1" in response.answer
        assert "ord-2" not in response.answer

    async def test_list_orders_empty(self) -> None:
        worker = OrderWorker(create_order_registry(InMemoryCommerceAdapter()))
        response = await worker.list_orders(context=_ctx())
        assert response.answer == "You don't have any orders on your account yet."
