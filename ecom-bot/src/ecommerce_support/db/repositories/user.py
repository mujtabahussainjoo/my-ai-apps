"""User repository."""

from __future__ import annotations

from ecommerce_support.db.models import User as UserRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import UserProfile


def _to_profile(row: UserRow) -> UserProfile:
    return UserProfile(
        user_id=row.id,
        email=row.email,
        display_name=row.display_name,
        created_at=row.created_at,
    )


class UserRepository(BaseRepository):
    """Read/write customer identity references."""

    async def get(self, user_id: str) -> UserProfile | None:
        row = await self.session.get(UserRow, user_id)
        return _to_profile(row) if row is not None else None

    async def upsert(
        self, *, user_id: str, email: str, display_name: str | None = None
    ) -> UserProfile:
        row = await self.session.get(UserRow, user_id)
        normalized = email.lower()
        if row is None:
            row = UserRow(id=user_id, email=normalized, display_name=display_name)
            self.session.add(row)
        else:
            row.email = normalized
            row.display_name = display_name
        await self.session.flush()
        return _to_profile(row)
