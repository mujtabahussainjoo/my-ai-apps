"""Order worker: order lookup, tracking, return eligibility, and order lists (FR-020 / FR-039).

The worker is a thin, framework-free facade over the order tools: it invokes them through the typed
registry (argument validation + ownership + audit) and renders a deterministic, data-only answer.
It never invents order data — unknown or unauthorized orders become a not-found message, and tool
failures a neutral retry message.
"""

from __future__ import annotations

from collections.abc import Callable

from ecommerce_support.schemas.agents import AgentResponse, ToolContext
from ecommerce_support.schemas.enums import ToolCallStatus
from ecommerce_support.tools.registry import ToolRegistry

Render = Callable[[dict[str, object]], str]

_NOT_FOUND_MESSAGE = "I couldn't find that order on your account."
_ERROR_MESSAGE = "I ran into a problem fetching that order. Please try again."


def _money(value: object, currency: object) -> str:
    return f"{value} {currency}"


def _render_order(output: dict[str, object]) -> str:
    order = output.get("order")
    if not isinstance(order, dict):
        return _ERROR_MESSAGE
    items = order.get("items")
    item_count = len(items) if isinstance(items, list) else 0
    return (
        f"Order {order.get('id')} is currently {order.get('status')}. "
        f"Total: {_money(order.get('total'), order.get('currency', 'USD'))}. "
        f"Placed on {str(order.get('placed_at', ''))[:10]}. {item_count} item(s)."
    )


def _render_shipment(output: dict[str, object]) -> str:
    order_id = output.get("order_id")
    status = output.get("status")
    shipment = output.get("shipment")
    if not isinstance(shipment, dict):
        return f"Order {order_id} is currently {status} and has no shipment tracking yet."
    text = (
        f"Order {order_id} is {status}. Shipment is {shipment.get('status')} via "
        f"{shipment.get('carrier')}, tracking {shipment.get('tracking_number')}."
    )
    estimated = shipment.get("estimated_delivery")
    if estimated:
        text += f" Estimated delivery: {str(estimated)[:10]}."
    return text


def _render_eligibility(output: dict[str, object]) -> str:
    eligibility = output.get("eligibility")
    if not isinstance(eligibility, dict):
        return _ERROR_MESSAGE
    decision = "eligible for return" if eligibility.get("eligible") else "not eligible for return"
    return f"Order {eligibility.get('order_id')} is {decision}. {eligibility.get('reason', '')}".strip()


def _render_orders(output: dict[str, object]) -> str:
    orders = output.get("orders")
    if not isinstance(orders, list) or not orders:
        return "You don't have any orders on your account yet."
    lines = [f"You have {output.get('total', 0)} order(s); showing {len(orders)}:"]
    for order in orders:
        if isinstance(order, dict):
            lines.append(
                f"- {order.get('id')}: {order.get('status')} — "
                f"{_money(order.get('total'), order.get('currency', 'USD'))}"
            )
    return "\n".join(lines)


class OrderWorker:
    """Typed facade over the order tools for the graph to call."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def get_order(self, order_id: str, *, context: ToolContext) -> AgentResponse:
        return await self._call(
            "get_order", {"order_id": order_id}, context=context, render=_render_order
        )

    async def track_shipment(self, order_id: str, *, context: ToolContext) -> AgentResponse:
        return await self._call(
            "track_shipment", {"order_id": order_id}, context=context, render=_render_shipment
        )

    async def return_eligibility(self, order_id: str, *, context: ToolContext) -> AgentResponse:
        return await self._call(
            "return_eligibility",
            {"order_id": order_id},
            context=context,
            render=_render_eligibility,
        )

    async def list_orders(
        self, *, context: ToolContext, limit: int = 10, offset: int = 0
    ) -> AgentResponse:
        return await self._call(
            "list_orders",
            {"limit": limit, "offset": offset},
            context=context,
            render=_render_orders,
        )

    async def _call(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        context: ToolContext,
        render: Render,
    ) -> AgentResponse:
        result = await self._registry.invoke(name, arguments, context=context)
        execution = result.to_execution()
        if result.status is not ToolCallStatus.OK or result.output is None:
            answer = _NOT_FOUND_MESSAGE if result.error == "Order not found." else _ERROR_MESSAGE
        else:
            answer = render(result.output)
        return AgentResponse(agent=context.agent, answer=answer, tool_executions=[execution])
