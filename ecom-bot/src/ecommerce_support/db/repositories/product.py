"""Product catalog repository (search, detail, stock)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select

from ecommerce_support.db.models import Product as ProductRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import Product, ProductSearchQuery, ProductSummary, StockInfo


def _to_product(row: ProductRow) -> Product:
    return Product(
        id=row.id,
        sku=row.sku,
        name=row.name,
        description=row.description,
        category=row.category,
        price=row.price,
        currency=row.currency,
        stock_status=row.stock_status,
        stock_quantity=row.stock_quantity,
        attributes=dict(row.attributes),
    )


def _to_summary(row: ProductRow) -> ProductSummary:
    return ProductSummary(
        id=row.id,
        sku=row.sku,
        name=row.name,
        category=row.category,
        price=row.price,
        currency=row.currency,
        stock_status=row.stock_status,
    )


class ProductRepository(BaseRepository):
    """Read/write catalog products used by the product worker and seed script."""

    async def get(self, product_id: str) -> Product | None:
        row = await self.session.get(ProductRow, product_id)
        return _to_product(row) if row is not None else None

    async def get_by_sku(self, sku: str) -> Product | None:
        row = await self.session.scalar(select(ProductRow).where(ProductRow.sku == sku))
        return _to_product(row) if row is not None else None

    async def stock_info(self, product_id: str) -> StockInfo | None:
        row = await self.session.get(ProductRow, product_id)
        if row is None:
            return None
        return StockInfo(
            product_id=row.id,
            status=row.stock_status,
            quantity=row.stock_quantity,
        )

    async def search(self, query: ProductSearchQuery) -> tuple[list[ProductSummary], int]:
        conditions = []
        if query.query:
            pattern = f"%{query.query}%"
            conditions.append(or_(ProductRow.name.ilike(pattern), ProductRow.sku.ilike(pattern)))
        if query.category:
            conditions.append(ProductRow.category == query.category)
        if query.min_price is not None:
            conditions.append(ProductRow.price >= query.min_price)
        if query.max_price is not None:
            conditions.append(ProductRow.price <= query.max_price)

        total = await self.session.scalar(
            select(func.count()).select_from(ProductRow).where(*conditions)
        )
        stmt = (
            select(ProductRow)
            .where(*conditions)
            .order_by(ProductRow.name.asc())
            .limit(query.limit)
            .offset(query.offset)
        )
        rows = list((await self.session.scalars(stmt)).all())
        return [_to_summary(row) for row in rows], int(total or 0)

    async def list_products(
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[ProductSummary], int]:
        return await self.search(ProductSearchQuery(limit=limit, offset=offset))

    async def upsert_many(self, products: Sequence[Product]) -> int:
        """Insert or update products by primary key; returns the number processed."""
        for product in products:
            row = await self.session.get(ProductRow, product.id)
            if row is None:
                row = ProductRow(id=product.id)
                self.session.add(row)
            row.sku = product.sku
            row.name = product.name
            row.description = product.description
            row.category = product.category
            row.price = product.price
            row.currency = product.currency
            row.stock_status = product.stock_status
            row.stock_quantity = product.stock_quantity
            row.attributes = dict(product.attributes)
        await self.session.flush()
        return len(products)
