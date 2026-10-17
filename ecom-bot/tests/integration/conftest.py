"""Shared fixtures for integration tests.

Requires the compose database service (`make db-up`) with migrations applied
(`make migrate`). Skipped automatically when no database is reachable, so the default
`make test` run needs no Docker/credentials.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from ecommerce_support.core.config import Settings


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """A live engine, or skip if PostgreSQL cannot be reached."""
    eng = create_async_engine(settings.database.url, pool_pre_ping=True)
    try:
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        await eng.dispose()
        pytest.skip(f"PostgreSQL not reachable at {settings.database.url}: {type(exc).__name__}")
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session bound to a transaction that is always rolled back.

    Repositories only ``flush`` (never ``commit``), so every test runs against the real
    schema yet leaves no rows behind.
    """
    async with engine.connect() as conn:
        trans = await conn.begin()
        sess = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield sess
        finally:
            await sess.close()
            if trans.is_active:
                await trans.rollback()
