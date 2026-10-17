"""Integration tests for PostgreSQL connectivity and pgvector availability.

Require the compose database service (`make db-up`) with migrations applied
(`make migrate`). Skipped automatically when no database is reachable, so the
default `make test` run needs no Docker/credentials.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


async def test_connection_executes_trivial_query(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        result = await conn.scalar(text("SELECT 1"))
    assert result == 1


async def test_pgvector_extension_is_available(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        extversion = await conn.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
    assert extversion is not None, "pgvector extension missing — run `make migrate`"


async def test_alembic_revision_is_applied(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        applied = await conn.scalar(text("SELECT count(*) FROM alembic_version"))
    assert applied and applied > 0, "no Alembic revision applied — run `make migrate`"
