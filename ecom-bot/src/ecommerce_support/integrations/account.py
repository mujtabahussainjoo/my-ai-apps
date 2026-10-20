"""Account adapter contracts (FR-023 / INT-003 spirit).

Account data sits behind :class:`AccountAdapter` so the account worker never touches the ORM and
tests run without a database. The mock/fixture adapter reads the ``users`` table; a real identity
backend would implement the same interface. Adapters expose **only** non-secret profile fields
(no passwords, tokens, or credentials).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ecommerce_support.schemas import UserProfile


class AccountAdapter(ABC):
    """Read interface over customer identity/account data (non-secret fields only)."""

    @abstractmethod
    async def get_profile(self, user_id: str) -> UserProfile | None:
        """Return the public profile for ``user_id`` (never credentials), or ``None``."""

    @abstractmethod
    async def order_count(self, user_id: str) -> int:
        """Return how many orders ``user_id`` has placed."""
