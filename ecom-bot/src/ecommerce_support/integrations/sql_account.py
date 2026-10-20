"""Fixture account adapter backed by PostgreSQL seed data (FR-023).

Mock/fixture-only: reads the ``users`` table via the repository and counts orders. Exposes only
non-secret profile fields; the identity table holds no credentials (those live in the real IdP).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.db.repositories.order import OrderRepository
from ecommerce_support.db.repositories.user import UserRepository
from ecommerce_support.integrations.account import AccountAdapter
from ecommerce_support.schemas import UserProfile


class SqlAccountAdapter(AccountAdapter):
    """Fixture account adapter reading the seeded ``users``/``orders`` tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_profile(self, user_id: str) -> UserProfile | None:
        return await UserRepository(self._session).get(user_id)

    async def order_count(self, user_id: str) -> int:
        _summaries, total = await OrderRepository(self._session).list_for_customer(user_id, limit=1)
        return total
