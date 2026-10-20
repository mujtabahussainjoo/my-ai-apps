"""Product worker: catalog search, details, and stock answers (FR-021).

Framework-free facade over the product tools. All catalog facts (names, prices, stock) come from
the commerce adapter via the tools; the worker only formats them, so it can never invent a price
or availability.
"""

from __future__ import annotations

from collections.abc import Callable

from ecommerce_support.schemas.agents import AgentResponse, ToolContext
from ecommerce_support.schemas.enums import ToolCallStatus
from ecommerce_support.tools.registry import ToolRegistry

_Render = Callable[[dict[str, object]], str]

_NOT_FOUND_MESSAGE = "I couldn't find that product."
_ERROR_MESSAGE = "I ran into a problem looking that up. Please try again."
_EMPTY_SEARCH_MESSAGE = "I couldn't find any products matching that."


def _money(value: object, currency: object) -> str:
    return f"{value} {currency}"


def _render_search(output: dict[str, object]) -> str:
    products = output.get("products")
    if not isinstance(products, list) or not products:
        return _EMPTY_SEARCH_MESSAGE
    lines = [f"I found {output.get('total', len(products))} product(s); showing {len(products)}:"]
    for product in products:
        if isinstance(product, dict):
            lines.append(
                f"- {product.get('name')} ({product.get('sku')}): "
                f"{_money(product.get('price'), product.get('currency', 'USD'))} — "
                f"{product.get('stock_status')}"
            )
    return "\n".join(lines)


def _render_product(output: dict[str, object]) -> str:
    product = output.get("product")
    if not isinstance(product, dict):
        return _ERROR_MESSAGE
    parts = [
        f"{product.get('name')} ({product.get('sku')})",
        f"Price: {_money(product.get('price'), product.get('currency', 'USD'))}.",
        f"Category: {product.get('category')}.",
        f"Availability: {product.get('stock_status')}.",
    ]
    description = product.get("description")
    if description:
        parts.append(str(description))
    return " ".join(parts)


def _render_stock(output: dict[str, object]) -> str:
    stock = output.get("stock")
    if not isinstance(stock, dict):
        return _ERROR_MESSAGE
    quantity = stock.get("quantity")
    available = f" ({quantity} available)" if isinstance(quantity, int) and quantity > 0 else ""
    return f"Product {stock.get('product_id')} is {stock.get('status')}{available}."


class ProductWorker:
    """Typed facade over the product tools for the graph to call."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def search(
        self,
        *,
        context: ToolContext,
        query: str | None = None,
        category: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> AgentResponse:
        return await self._call(
            "search_products",
            {
                "query": query,
                "category": category,
                "limit": limit,
                "offset": offset,
            },
            context=context,
            render=_render_search,
        )

    async def get_product(self, product_id: str, *, context: ToolContext) -> AgentResponse:
        return await self._call(
            "get_product", {"product_id": product_id}, context=context, render=_render_product
        )

    async def check_stock(self, product_id: str, *, context: ToolContext) -> AgentResponse:
        return await self._call(
            "check_stock", {"product_id": product_id}, context=context, render=_render_stock
        )

    async def _call(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        context: ToolContext,
        render: _Render,
    ) -> AgentResponse:
        result = await self._registry.invoke(name, arguments, context=context)
        execution = result.to_execution()
        if result.status is not ToolCallStatus.OK or result.output is None:
            answer = _NOT_FOUND_MESSAGE if result.error == "Product not found." else _ERROR_MESSAGE
        else:
            answer = render(result.output)
        return AgentResponse(agent=context.agent, answer=answer, tool_executions=[execution])
