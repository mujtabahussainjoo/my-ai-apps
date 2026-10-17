"""Async engine/session management and the database readiness check."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ecommerce_support.core.config import Settings, get_settings
from ecommerce_support.core.readiness import CheckResult, register_readiness_check

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Return the process-wide async engine (created lazily, cached)."""
    global _engine
    if _engine is None:
        cfg = (settings or get_settings()).database
        _engine = create_async_engine(
            cfg.url,
            echo=cfg.echo,
            pool_size=cfg.pool_size,
            max_overflow=cfg.max_overflow,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """Return the cached async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(settings), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope: commits on success, rolls back on exception."""
    async with get_session_factory().begin() as session:
        yield session


async def close_engine() -> None:
    """Dispose the engine and reset caches (shutdown/tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def check_database() -> CheckResult:
    """Readiness check: verify a trivial query succeeds."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        return CheckResult("database", False, type(exc).__name__)
    return CheckResult("database", True, "connected")


register_readiness_check(check_database)
