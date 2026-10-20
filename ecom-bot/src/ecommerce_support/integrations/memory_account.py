"""In-memory account adapter for unit tests and framework-free agent runs (FR-023)."""

from __future__ import annotations

from collections.abc import Iterable

from ecommerce_support.integrations.account import AccountAdapter
from ecommerce_support.schemas import UserProfile


class InMemoryAccountAdapter(AccountAdapter):
    """Mock account adapter holding profiles and order counts in memory."""

    def __init__(
        self,
        *,
        profiles: Iterable[UserProfile] = (),
        order_counts: dict[str, int] | None = None,
    ) -> None:
        self._profiles: dict[str, UserProfile] = {p.user_id: p for p in profiles}
        self._order_counts: dict[str, int] = dict(order_counts or {})

    def add_profile(self, profile: UserProfile) -> None:
        self._profiles[profile.user_id] = profile

    async def get_profile(self, user_id: str) -> UserProfile | None:
        return self._profiles.get(user_id)

    async def order_count(self, user_id: str) -> int:
        return self._order_counts.get(user_id, 0)
