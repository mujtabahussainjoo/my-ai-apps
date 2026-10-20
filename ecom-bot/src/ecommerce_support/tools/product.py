"""Product tools: catalog search, product details, and stock checks (FR-021/FR-039).

Catalog data comes exclusively from the commerce adapter — these tools never invent prices or
stock (FR-021). Products are public, so no authentication is required, but only the product agent
may call them (per-agent allowlist).
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.integrations.commerce import CommerceAdapter
from ecommerce_support.schemas import ProductSearchQuery
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName
from ecommerce_support.tools.audit import AuditHook
from ecommerce_support.tools.registry import Tool, ToolRegistry, create_tool_registry

_PRODUCT_AGENTS = frozenset({AgentName.PRODUCT})


class SearchProductsArgs(BaseModel):
    query: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    min_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    max_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0)


class GetProductArgs(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)


class CheckStockArgs(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)


class SearchProductsTool(Tool[SearchProductsArgs]):
    """Search the catalog (summary results only)."""

    name = "search_products"
    description = "Search the product catalog by text, category, and price range."
    arguments_model = SearchProductsArgs
    allowed_agents = _PRODUCT_AGENTS

    def __init__(self, adapter: CommerceAdapter) -> None:
        self._adapter = adapter

    async def run(self, arguments: SearchProductsArgs, context: ToolContext) -> dict[str, object]:
        query = ProductSearchQuery(
            query=arguments.query,
            category=arguments.category,
            min_price=arguments.min_price,
            max_price=arguments.max_price,
            limit=arguments.limit,
            offset=arguments.offset,
        )
        results, total = await self._adapter.search_products(query)
        return {"products": [item.model_dump(mode="json") for item in results], "total": total}

    def summarize(self, result: dict[str, object]) -> str:
        products = result.get("products")
        count = len(products) if isinstance(products, list) else 0
        return f"found {count} products"


class GetProductTool(Tool[GetProductArgs]):
    """Return full details for a single product."""

    name = "get_product"
    description = "Return full details (price, specs, stock) for a product id."
    arguments_model = GetProductArgs
    allowed_agents = _PRODUCT_AGENTS

    def __init__(self, adapter: CommerceAdapter) -> None:
        self._adapter = adapter

    async def run(self, arguments: GetProductArgs, context: ToolContext) -> dict[str, object]:
        product = await self._adapter.get_product(arguments.product_id)
        if product is None:
            raise NotFoundError("Product not found.", details={"product_id": arguments.product_id})
        return {"product": product.model_dump(mode="json")}

    def summarize(self, result: dict[str, object]) -> str:
        product = result.get("product")
        product_id = product.get("id") if isinstance(product, dict) else "?"
        return f"fetched product {product_id}"


class CheckStockTool(Tool[CheckStockArgs]):
    """Return stock availability for a single product."""

    name = "check_stock"
    description = "Check stock availability for a product id."
    arguments_model = CheckStockArgs
    allowed_agents = _PRODUCT_AGENTS

    def __init__(self, adapter: CommerceAdapter) -> None:
        self._adapter = adapter

    async def run(self, arguments: CheckStockArgs, context: ToolContext) -> dict[str, object]:
        stock = await self._adapter.stock_info(arguments.product_id)
        if stock is None:
            raise NotFoundError("Product not found.", details={"product_id": arguments.product_id})
        return {"stock": stock.model_dump(mode="json")}

    def summarize(self, result: dict[str, object]) -> str:
        stock = result.get("stock")
        product_id = stock.get("product_id") if isinstance(stock, dict) else "?"
        return f"checked stock for {product_id}"


def create_product_registry(
    adapter: CommerceAdapter, *, audit_hook: AuditHook | None = None
) -> ToolRegistry:
    """Build a registry containing the product tools bound to ``adapter``."""
    return create_tool_registry(
        [
            SearchProductsTool(adapter),
            GetProductTool(adapter),
            CheckStockTool(adapter),
        ],
        audit_hook=audit_hook,
    )
