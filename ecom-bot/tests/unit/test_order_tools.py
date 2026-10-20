"""Unit tests for order tools: adapter wiring + ownership enforcement (TASK-023)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ecommerce_support.core.exceptions import AuthorizationError, NotFoundError
from ecommerce_support.integrations import InMemoryCommerceAdapter
from ecommerce_support.schemas import Order, OrderItem, OrderStatus
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools import create_order_registry
from ecommerce_support.tools.order import (
    GetOrderArgs,
    GetOrderTool,
    ListOrdersArgs,
    ListOrdersTool,
    ReturnEligibilityArgs,
    ReturnEligibilityTool,
    TrackShipmentArgs,
    TrackShipmentTool,
)


def _order(order_id: str, *, customer_id: str = "cust-1") -> Order:
    return Order(
        id=order_id,
        customer_id=customer_id,
        status=OrderStatus.DELIVERED,
        total=Decimal("19.98"),
        placed_at=datetime.now(UTC),
        items=[
            OrderItem(
                product_id="prd-1",
                name="Widget",
                quantity=1,
                unit_price=Decimal("19.98"),
                line_total=Decimal("19.98"),
            )
        ],
    )


def _ctx(agent: AgentName = AgentName.ORDER, user_id: str | None = "cust-1") -> ToolContext:
    return ToolContext(agent=agent, user_id=user_id, conversation_id="conv-1")


@pytest.fixture
def adapter() -> InMemoryCommerceAdapter:
    return InMemoryCommerceAdapter(orders=[_order("ord-1"), _order("ord-2", customer_id="cust-9")])


class TestGetOrderTool:
    async def test_returns_owned_order(self, adapter: InMemoryCommerceAdapter) -> None:
        tool = GetOrderTool(adapter)
        output = await tool.run(GetOrderArgs(order_id="ord-1"), _ctx())
        assert output["order"]["id"] == "ord-1"  # type: ignore[index]
        assert tool.summarize(output) == "fetched order ord-1"

    async def test_unknown_order_is_not_found(self, adapter: InMemoryCommerceAdapter) -> None:
        with pytest.raises(NotFoundError):
            await GetOrderTool(adapter).run(GetOrderArgs(order_id="missing"), _ctx())

    async def test_other_customers_order_is_not_found(
        self, adapter: InMemoryCommerceAdapter
    ) -> None:
        with pytest.raises(NotFoundError, match="Order not found"):
            await GetOrderTool(adapter).run(GetOrderArgs(order_id="ord-2"), _ctx())


class TestTrackShipmentTool:
    async def test_untracked_order_returns_none(self, adapter: InMemoryCommerceAdapter) -> None:
        output = await TrackShipmentTool(adapter).run(TrackShipmentArgs(order_id="ord-1"), _ctx())
        assert output["order_id"] == "ord-1"
        assert output["shipment"] is None

    async def test_other_customer_denied(self, adapter: InMemoryCommerceAdapter) -> None:
        with pytest.raises(NotFoundError):
            await TrackShipmentTool(adapter).run(TrackShipmentArgs(order_id="ord-2"), _ctx())


class TestReturnEligibilityTool:
    async def test_eligible_decision(self, adapter: InMemoryCommerceAdapter) -> None:
        output = await ReturnEligibilityTool(adapter).run(
            ReturnEligibilityArgs(order_id="ord-1"), _ctx()
        )
        assert output["eligibility"]["eligible"] is True  # type: ignore[index]

    async def test_other_customer_denied(self, adapter: InMemoryCommerceAdapter) -> None:
        with pytest.raises(NotFoundError):
            await ReturnEligibilityTool(adapter).run(
                ReturnEligibilityArgs(order_id="ord-2"), _ctx()
            )


class TestListOrdersTool:
    async def test_lists_only_own_orders(self, adapter: InMemoryCommerceAdapter) -> None:
        output = await ListOrdersTool(adapter).run(ListOrdersArgs(), _ctx())
        assert output["total"] == 1
        assert [o["id"] for o in output["orders"]] == ["ord-1"]  # type: ignore[index,union-attr]


class TestRegistryIntegration:
    async def test_owned_lookup_through_registry(self, adapter: InMemoryCommerceAdapter) -> None:
        registry = create_order_registry(adapter)
        result = await registry.invoke("get_order", {"order_id": "ord-1"}, context=_ctx())
        assert result.status is ToolCallStatus.OK
        assert result.output is not None and result.output["order"]["id"] == "ord-1"  # type: ignore[index]

    async def test_cross_customer_call_is_error_without_leak(
        self, adapter: InMemoryCommerceAdapter
    ) -> None:
        registry = create_order_registry(adapter)
        result = await registry.invoke("get_order", {"order_id": "ord-2"}, context=_ctx())
        assert result.status is ToolCallStatus.ERROR
        assert result.error == "Order not found."

    async def test_order_tools_reject_other_agents(self, adapter: InMemoryCommerceAdapter) -> None:
        registry = create_order_registry(adapter)
        with pytest.raises(AuthorizationError):
            await registry.invoke(
                "get_order", {"order_id": "ord-1"}, context=_ctx(agent=AgentName.PRODUCT)
            )
