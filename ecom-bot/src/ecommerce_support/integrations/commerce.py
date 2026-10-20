"""Commerce adapter contracts (FR-041 / INT-003).

The commerce backend sits behind :class:`CommerceAdapter`. v1 ships a mock/fixture adapter that
reads seeded demo data from PostgreSQL; a real Magento/Adobe Commerce adapter is a documented
extension point (see ``docs/commerce-adapter.md``) and must implement the same interface.

Adapters are plain Python — no framework imports — and return Pydantic schemas, never ORM objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ecommerce_support.schemas import (
    Order,
    OrderSummary,
    Product,
    ProductSearchQuery,
    ProductSummary,
    ReturnEligibility,
    Shipment,
    StockInfo,
)


class CommerceAdapter(ABC):
    """Read interface over the commerce backend (orders + catalog)."""

    @abstractmethod
    async def get_order(self, order_id: str) -> Order | None:
        """Return the order with ``order_id`` (with items + shipment) or ``None``."""

    @abstractmethod
    async def list_orders(
        self, customer_id: str, *, limit: int = 10, offset: int = 0
    ) -> tuple[list[OrderSummary], int]:
        """Return a page of ``customer_id``'s orders plus the total count."""

    @abstractmethod
    async def track_shipment(self, order_id: str) -> Shipment | None:
        """Return the shipment/tracking record for an order, or ``None`` if untracked."""

    @abstractmethod
    async def return_eligibility(self, order_id: str) -> ReturnEligibility | None:
        """Return the return-eligibility decision for an order, or ``None`` if unknown."""

    @abstractmethod
    async def search_products(self, query: ProductSearchQuery) -> tuple[list[ProductSummary], int]:
        """Search the catalog, returning a page of summaries and the total count."""

    @abstractmethod
    async def get_product(self, product_id: str) -> Product | None:
        """Return full product details, or ``None`` if the product is unknown."""

    @abstractmethod
    async def stock_info(self, product_id: str) -> StockInfo | None:
        """Return stock availability for a product, or ``None`` if the product is unknown."""
