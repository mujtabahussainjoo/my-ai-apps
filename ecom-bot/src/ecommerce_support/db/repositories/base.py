"""Repository layer: translate between ORM rows and typed schemas.

Repositories are the only place that touches ORM objects. They never ``commit`` — the caller
owns the transaction (see ``db.session.session_scope``) — and they never return ORM objects,
only Pydantic schemas or primitives.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Common constructor for all repositories."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
