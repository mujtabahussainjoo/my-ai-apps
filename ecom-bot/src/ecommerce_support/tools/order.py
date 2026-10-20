"""Order tools: order lookup, shipment tracking, return eligibility, order listing (FR-020/039).

Every tool enforces order ownership in code (SEC-002/FR-040): a customer may only see orders whose
``customer_id`` matches the authenticated ``ToolContext.user_id``; anything else is reported as
*not found* so existence is never leaked. Tools are registered with the typed registry, which adds
argument validation, per-agent allowlists, and redacted auditing.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.integrations.commerce import CommerceAdapter
from ecommerce_support.schemas import Order
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName
from ecommerce_support.tools.audit import AuditHook
from ecommerce_support.tools.registry import Tool, ToolRegistry, create_tool_registry

_ORDER_AGENTS = frozenset({AgentName.ORDER})


class GetOrderArgs(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)


class TrackShipmentArgs(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)


class ReturnEligibilityArgs(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)


class ListOrdersArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


def _require_owned(order: Order | None, context: ToolContext) -> Order:
    """Return ``order`` iff the caller owns it, else raise not-found (no existence leak)."""
    if order is None or order.customer_id != context.user_id:
        raise NotFoundError(
            "Order not found.",
            details={"order_id": order.id if order is not None else None},
        )
    return order


class GetOrderTool(Tool[GetOrderArgs]):
    """Retrieve one of the authenticated customer's orders."""

    name = "get_order"
    description = "Retrieve an order (items, totals, status) owned by the signed-in customer."
    arguments_model = GetOrderArgs
    allowed_agents = _ORDER_AGENTS
    requires_auth = True

    def __init__(self, adapter: CommerceAdapter) -> None:
        self._adapter = adapter

    async def run(self, arguments: GetOrderArgs, context: ToolContext) -> dict[str, object]:
        order = _require_owned(await self._adapter.get_order(arguments.order_id), context)
        return {"order": order.model_dump(mode="json")}

    def summarize(self, result: dict[str, object]) -> str:
        order = result.get("order")
        order_id = order.get("id") if isinstance(order, dict) else "?"
        return f"fetched order {order_id}"


class TrackShipmentTool(Tool[TrackShipmentArgs]):
    """Return shipment/tracking state for one of the customer's orders."""

    name = "track_shipment"
    description = "Track the shipment for an order owned by the signed-in customer."
    arguments_model = TrackShipmentArgs
    allowed_agents = _ORDER_AGENTS
    requires_auth = True

    def __init__(self, adapter: CommerceAdapter) -> None:
        self._adapter = adapter

    async def run(self, arguments: TrackShipmentArgs, context: ToolContext) -> dict[str, object]:
        order = _require_owned(await self._adapter.get_order(arguments.order_id), context)
        shipment = await self._adapter.track_shipment(order.id)
        return {
            "order_id": order.id,
            "status": order.status.value,
            "shipment": shipment.model_dump(mode="json") if shipment is not None else None,
        }

    def summarize(self, result: dict[str, object]) -> str:
        return f"tracked order {result.get('order_id')}"


class ReturnEligibilityTool(Tool[ReturnEligibilityArgs]):
    """Return the return-eligibility decision for one of the customer's orders."""

    name = "return_eligibility"
    description = "Check whether an order owned by the signed-in customer can be returned."
    arguments_model = ReturnEligibilityArgs
    allowed_agents = _ORDER_AGENTS
    requires_auth = True

    def __init__(self, adapter: CommerceAdapter) -> None:
        self._adapter = adapter

    async def run(
        self, arguments: ReturnEligibilityArgs, context: ToolContext
    ) -> dict[str, object]:
        order = _require_owned(await self._adapter.get_order(arguments.order_id), context)
        eligibility = await self._adapter.return_eligibility(order.id)
        if eligibility is None:
            raise NotFoundError("Order not found.", details={"order_id": order.id})
        return {"eligibility": eligibility.model_dump(mode="json")}

    def summarize(self, result: dict[str, object]) -> str:
        eligibility = result.get("eligibility")
        order_id = eligibility.get("order_id") if isinstance(eligibility, dict) else "?"
        return f"checked return eligibility for {order_id}"


class ListOrdersTool(Tool[ListOrdersArgs]):
    """List the authenticated customer's own orders (ownership is intrinsic)."""

    name = "list_orders"
    description = "List orders owned by the signed-in customer, newest first."
    arguments_model = ListOrdersArgs
    allowed_agents = _ORDER_AGENTS
    requires_auth = True

    def __init__(self, adapter: CommerceAdapter) -> None:
        self._adapter = adapter

    async def run(self, arguments: ListOrdersArgs, context: ToolContext) -> dict[str, object]:
        if not context.user_id:
            raise NotFoundError("Customer not found.")
        summaries, total = await self._adapter.list_orders(
            context.user_id, limit=arguments.limit, offset=arguments.offset
        )
        return {
            "orders": [summary.model_dump(mode="json") for summary in summaries],
            "total": total,
        }

    def summarize(self, result: dict[str, object]) -> str:
        orders = result.get("orders")
        count = len(orders) if isinstance(orders, list) else 0
        return f"listed {count} orders"


def create_order_registry(
    adapter: CommerceAdapter, *, audit_hook: AuditHook | None = None
) -> ToolRegistry:
    """Build a registry containing the order tools bound to ``adapter``."""
    return create_tool_registry(
        [
            GetOrderTool(adapter),
            TrackShipmentTool(adapter),
            ReturnEligibilityTool(adapter),
            ListOrdersTool(adapter),
        ],
        audit_hook=audit_hook,
    )
