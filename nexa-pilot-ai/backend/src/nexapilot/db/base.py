"""SQLAlchemy engine and session helpers."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from nexapilot.core.config import Settings, get_settings

_engines: dict[str, Engine] = {}
_factories: dict[str, sessionmaker[Session]] = {}


def _engine_key(settings: Settings) -> str:
    return settings.effective_database_url


def create_db_engine(database_url: str) -> Engine:
    """Create an engine with SQLite-friendly pragmas."""
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(database_url, future=True, connect_args=connect_args)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def get_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    key = _engine_key(settings)
    if key not in _engines:
        _engines[key] = create_db_engine(key)
        _factories[key] = sessionmaker(bind=_engines[key], expire_on_commit=False, future=True)
    return _engines[key]


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    settings = settings or get_settings()
    get_engine(settings)
    key = _engine_key(settings)
    factory = _factories[key]
    if factory is None:  # pragma: no cover - defensive
        raise RuntimeError("session factory not initialised")
    return factory


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Transactional session scope."""
    factory = get_session_factory(settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engines() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _factories.clear()


def initialize_database(settings: Settings | None = None) -> Path:
    """Create the SQLite file and run migrations up to head.

    Returns the path of the SQLite database file.
    """
    from alembic import command
    from alembic.config import Config

    settings = settings or get_settings()
    url = settings.effective_database_url
    if url.startswith("sqlite:///"):
        db_path = Path(url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:  # pragma: no cover - non-sqlite deployments
        db_path = Path()

    backend_root = _backend_root()
    alembic_ini = backend_root / "alembic.ini"
    alembic_dir = backend_root / "alembic"

    if not alembic_dir.is_dir():
        # Frozen builds without bundled migrations still need a usable schema.
        from nexapilot.db.models import Base

        Base.metadata.create_all(get_engine(settings))
        return db_path

    cfg = Config(str(alembic_ini)) if alembic_ini.exists() else Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return db_path


def _backend_root() -> Path:
    """Locate bundled migration files in a source checkout or a frozen sidecar."""
    candidates: list[Path] = []
    frozen = getattr(sys, "_MEIPASS", None)
    if isinstance(frozen, str):
        candidates.extend([Path(frozen), Path(frozen).parent])
    candidates.append(Path(__file__).resolve().parents[3])
    for candidate in candidates:
        if (candidate / "alembic").is_dir():
            return candidate
    return candidates[-1]
