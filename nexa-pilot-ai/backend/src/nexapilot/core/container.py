"""Application container.

Holds the long-lived collaborators (settings, secret store, database session
factory, provider factory) and wires them together. Tests construct a container
with temporary directories and an in-memory secret store.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from nexapilot.core.config import Settings, get_settings
from nexapilot.core.secrets import SecretStore, build_secret_store
from nexapilot.db.base import create_db_engine


@dataclass
class Container:
    settings: Settings
    secrets: SecretStore
    session_factory: sessionmaker[Session]
    engine: Engine | None = field(default=None, repr=False)

    @classmethod
    def create(cls, settings: Settings | None = None) -> Container:
        settings = settings or get_settings()
        secrets = build_secret_store(settings.secret_backend)
        engine = create_db_engine(settings.effective_database_url)
        factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        return cls(settings=settings, secrets=secrets, session_factory=factory, engine=engine)

    @classmethod
    def for_testing(
        cls,
        tmp_path: Path,
        *,
        settings_overrides: dict[str, object] | None = None,
    ) -> Container:
        overrides: dict[str, object] = {
            "environment": "test",
            "database_url": f"sqlite:///{tmp_path / 'test.db'}",
            "secret_backend": "memory",
            "log_level": "WARNING",
        }
        overrides.update(settings_overrides or {})
        settings = Settings.model_validate(overrides)
        return cls.create(settings)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
