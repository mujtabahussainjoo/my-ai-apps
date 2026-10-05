"""Engine and session management.

The engine is created lazily and cached, because importing a module must never
open a socket: the CLI tools, the risk engine and the test suite all import from
here and most of them run without a database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.config import get_settings
from src.core.logging import get_logger

logger = get_logger(__name__)

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def build_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create an engine.

    ``pool_pre_ping`` guards against a connection that Postgres closed while it
    sat idle in the pool - common with a container that restarts overnight, and
    without it the next request fails with a connection error instead of
    reconnecting.
    """
    settings = get_settings()
    target = url or settings.sqlalchemy_url
    kwargs: dict[str, Any] = {
        "echo": echo,
        "pool_pre_ping": True,
        "future": True,
    }
    if target.startswith("postgresql"):
        kwargs.update(pool_size=10, max_overflow=20, pool_recycle=1800)
    else:
        # SQLite is only used by the offline tests; it has no server to ping.
        from sqlalchemy.pool import StaticPool

        kwargs.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(target, **kwargs)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine()
        logger.info("database_engine_created")
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception.

    Exceptions must never escape with a half-written ledger, so the rollback is
    unconditional and the session is always closed.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("database_transaction_failed")
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency with the same commit-or-rollback guarantee."""
    with session_scope() as session:
        yield session


def reset_engine() -> None:
    """Dispose of the cached engine. Used by tests and by ``migrate``."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def ping() -> bool:
    """Cheap liveness probe for ``/health``."""
    from sqlalchemy import text

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        logger.warning("database_ping_failed", error=str(exc), error_type=type(exc).__name__)
        return False