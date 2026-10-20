"""Security tests: order ownership is enforced in the tool layer (TASK-023, SEC-002/FR-040).

Cross-customer order access must be indistinguishable from a non-existent order: same not-found
outcome, no order data, and only a redacted audit signal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ecommerce_support.integrations import InMemoryCommerceAdapter
from ecommerce_support.schemas import Order, OrderItem, OrderStatus
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools import ToolRegistry, create_order_registry
from ecommerce_support.tools.audit import RecordingAuditHook

pytestmark = pytest.mark.security


def _order(order_id: str, *, customer_id: str) -> Order:
    return Order(
        id=order_id,
        customer_id=customer_id,
        status=OrderStatus.DELIVERED,
        total=Decimal("42.00"),
        placed_at=datetime(2026, 10, 1, tzinfo=UTC),
        items=[
            OrderItem(
                product_id="prd-1",
                name="Secret Widget",
                quantity=1,
                unit_price=Decimal("42.00"),
                line_total=Decimal("42.00"),
            )
        ],
    )


@pytest.fixture
def registry_and_hook() -> tuple[ToolRegistry, RecordingAuditHook]:
    hook = RecordingAuditHook()
    adapter = InMemoryCommerceAdapter(orders=[_order("ord-1", customer_id="cust-1")])
    return create_order_registry(adapter, audit_hook=hook), hook


def _ctx(user_id: str | None) -> ToolContext:
    return ToolContext(agent=AgentName.ORDER, user_id=user_id, conversation_id="conv-1")


class TestCrossCustomerAccess:
    async def test_other_customer_gets_not_found(self, registry_and_hook: tuple) -> None:
        registry, _ = registry_and_hook
        result = await registry.invoke("get_order", {"order_id": "ord-1"}, context=_ctx("attacker"))
        assert result.status is ToolCallStatus.ERROR
        assert result.error == "Order not found."
        assert result.output is None

    async def test_denial_does_not_leak_order_data(
        self, registry_and_hook: tuple[ToolRegistry, RecordingAuditHook]
    ) -> None:
        registry, _hook = registry_and_hook
        result = await registry.invoke("get_order", {"order_id": "ord-1"}, context=_ctx("cust-9"))
        blob = f"{result.output}{result.error}{result.summary}"
        assert "Secret Widget" not in blob
        assert "42.00" not in blob
        assert "cust-1" not in blob

    async def test_owner_sees_own_order(
        self, registry_and_hook: tuple[ToolRegistry, RecordingAuditHook]
    ) -> None:
        registry, _ = registry_and_hook
        context = ToolContext(agent=AgentName.ORDER, user_id="cust-1")
        result = await registry.invoke("get_order", {"order_id": "ord-1"}, context=context)
        assert result.status is ToolCallStatus.OK

    async def test_denial_does_not_leak_via_audit(
        self, registry_and_hook: tuple[ToolRegistry, RecordingAuditHook]
    ) -> None:
        registry, hook = registry_and_hook
        await registry.invoke("get_order", {"order_id": "ord-1"}, context=_ctx("cust-9"))
        assert "Secret Widget" not in str([event.detail for event in hook.events])
        assert "42.00" not in str([event.detail for event in hook.events])
