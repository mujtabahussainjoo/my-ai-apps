"""Unit tests for product tools and worker: catalog-backed, never inventing data (TASK-024)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ecommerce_support.agents import ProductWorker
from ecommerce_support.core.exceptions import AuthorizationError, NotFoundError
from ecommerce_support.integrations import InMemoryCommerceAdapter
from ecommerce_support.schemas import Product, StockStatus
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools import create_product_registry
from ecommerce_support.tools.product import (
    CheckStockArgs,
    CheckStockTool,
    GetProductArgs,
    GetProductTool,
    SearchProductsArgs,
    SearchProductsTool,
)


def _product(product_id: str, *, name: str = "Widget", price: str = "9.99") -> Product:
    return Product(
        id=product_id,
        sku=f"SKU-{product_id}",
        name=name,
        description=f"A {name}.",
        category="tools",
        price=Decimal(price),
        stock_status=StockStatus.IN_STOCK,
        stock_quantity=4,
    )


@pytest.fixture
def adapter() -> InMemoryCommerceAdapter:
    return InMemoryCommerceAdapter(
        products=[_product("prd-1", name="Hammer", price="9.99"), _product("prd-2", name="Drill")]
    )


def _ctx(agent: AgentName = AgentName.PRODUCT) -> ToolContext:
    return ToolContext(agent=agent, user_id=None, conversation_id="conv-1")


class TestProductTools:
    async def test_search_returns_catalog_data(self, adapter: InMemoryCommerceAdapter) -> None:
        output = await SearchProductsTool(adapter).run(SearchProductsArgs(query="hammer"), _ctx())
        assert output["total"] == 1
        assert output["products"][0]["sku"] == "SKU-prd-1"  # type: ignore[index]

    async def test_empty_search_returns_nothing(self, adapter: InMemoryCommerceAdapter) -> None:
        output = await SearchProductsTool(adapter).run(SearchProductsArgs(query="zzz"), _ctx())
        assert output["products"] == []
        assert output["total"] == 0

    async def test_get_product_details(self, adapter: InMemoryCommerceAdapter) -> None:
        output = await GetProductTool(adapter).run(GetProductArgs(product_id="prd-1"), _ctx())
        assert output["product"]["name"] == "Hammer"  # type: ignore[index]

    async def test_unknown_product_is_not_found(self, adapter: InMemoryCommerceAdapter) -> None:
        with pytest.raises(NotFoundError):
            await GetProductTool(adapter).run(GetProductArgs(product_id="nope"), _ctx())

    async def test_stock_check(self, adapter: InMemoryCommerceAdapter) -> None:
        output = await CheckStockTool(adapter).run(CheckStockArgs(product_id="prd-1"), _ctx())
        assert output["stock"]["quantity"] == 4  # type: ignore[index]

    async def test_unknown_stock_is_not_found(self, adapter: InMemoryCommerceAdapter) -> None:
        with pytest.raises(NotFoundError):
            await CheckStockTool(adapter).run(CheckStockArgs(product_id="zzz"), _ctx())


class TestProductRegistry:
    async def test_only_product_agent_allowed(self, adapter: InMemoryCommerceAdapter) -> None:
        registry = create_product_registry(adapter)
        with pytest.raises(AuthorizationError):
            await registry.invoke("search_products", {}, context=_ctx(AgentName.ORDER))

    async def test_unknown_product_through_registry_is_error(
        self, adapter: InMemoryCommerceAdapter
    ) -> None:
        registry = create_product_registry(adapter)
        result = await registry.invoke("get_product", {"product_id": "nope"}, context=_ctx())
        assert result.status is ToolCallStatus.ERROR
        assert result.error == "Product not found."


class TestProductWorker:
    @pytest.fixture
    def worker(self, adapter: InMemoryCommerceAdapter) -> ProductWorker:
        return ProductWorker(create_product_registry(adapter))

    async def test_search_answers_from_catalog(self, worker: ProductWorker) -> None:
        response = await worker.search(query="hammer", context=_ctx())
        assert "Hammer" in response.answer
        assert "9.99" in response.answer
        assert response.tool_executions[0].status is ToolCallStatus.OK

    async def test_empty_search_is_honest(self, worker: ProductWorker) -> None:
        response = await worker.search(query="zzz", context=_ctx())
        assert response.answer == "I couldn't find any products matching that."

    async def test_product_details(self, worker: ProductWorker) -> None:
        response = await worker.get_product("prd-1", context=_ctx())
        assert "Hammer" in response.answer
        assert "Price:" in response.answer

    async def test_unknown_product_is_polite(self, worker: ProductWorker) -> None:
        response = await worker.get_product("nope", context=_ctx())
        assert response.answer == "I couldn't find that product."

    async def test_stock_answer(self, worker: ProductWorker) -> None:
        response = await worker.check_stock("prd-1", context=_ctx())
        assert "in_stock" in response.answer
        assert "4 available" in response.answer
