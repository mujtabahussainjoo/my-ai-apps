"""Schema migrations.

A migration is a module named ``vNNN_snake_case`` exposing::

    def upgrade(engine: Engine) -> None: ...

The runner applies them in order inside a transaction and records the version,
a checksum of the file, and when it ran. The checksum matters: editing a
migration that has already been applied means databases are silently on
different schemas, so the runner refuses instead of ignoring it.

Deliberately not Alembic. The project needs ordered, recorded, transactional
DDL - not the ability to autogenerate diffs against a live database, which is
how schemas drift out of version control in the first place.
"""

from __future__ import annotations

import hashlib
import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    func,
    insert,
    select,
)
from sqlalchemy.engine import Connection, Engine

from src.core.logging import get_logger

logger = get_logger(__name__)

#: Built with SQLAlchemy types rather than raw SQL so the runner also works on
#: SQLite, which rejects TIMESTAMPTZ and now() and is what the offline tests use.
_metadata = MetaData()
VERSIONS_TABLE = Table(
    "schema_migrations",
    _metadata,
    Column("version", String(255), primary_key=True),
    Column("checksum", String(64), nullable=False),
    Column("applied_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    checksum: str
    module: object

    @property
    def description(self) -> str:
        return self.version


def _checksum(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()[:32]


def discover() -> list[Migration]:
    """Every migration in this package, in version order."""
    found: list[Migration] = []
    for info in pkgutil.iter_modules(__path__):
        if not info.name.startswith("v") or info.ispkg:
            continue
        source = Path(__file__).with_name(f"{info.name}.py").read_bytes()
        found.append(
            Migration(
                version=info.name.split("_", 1)[0],
                name=info.name,
                checksum=_checksum(source),
                module=importlib.import_module(f"{__name__}.{info.name}"),
            )
        )
    return sorted(found, key=lambda m: m.version)


def ensure_versions_table(conn: Connection) -> None:
    VERSIONS_TABLE.create(bind=conn, checkfirst=True)


def applied_versions(engine: Engine) -> dict[str, str]:
    with engine.begin() as conn:
        ensure_versions_table(conn)
    with engine.connect() as conn:
        # .mappings() keys each row by *column name*, so the keys must be read
        # explicitly: dict(records) would collapse every row into a single
        # {"version": ..., "checksum": ...} entry and hide all applied versions.
        records = (
            conn.execute(select(VERSIONS_TABLE.c.version, VERSIONS_TABLE.c.checksum))
            .mappings()
            .all()
        )
        return {record["version"]: record["checksum"] for record in records}


def pending(engine: Engine) -> list[Migration]:
    done = applied_versions(engine)
    return [m for m in discover() if m.version not in done]


def changed_migrations(engine: Engine) -> list[str]:
    """Applied migrations whose file content no longer matches the record."""
    done = applied_versions(engine)
    return [
        m.version
        for m in discover()
        if m.version in done and done[m.version] != m.checksum
    ]


def apply_migration(engine: Engine, migration: Migration) -> None:
    """Apply one migration atomically.

    A migration that half-applies leaves a database that passes a naive smoke
    test and then fails in production, so the DDL and the version record share
    one transaction.
    """
    logger.info("migration_applying", version=migration.version)
    with engine.begin() as conn:
        migration.module.upgrade(conn)  # type: ignore[attr-defined]
        conn.execute(
            insert(VERSIONS_TABLE).values(
                version=migration.version, checksum=migration.checksum
            )
        )
    logger.info("migration_applied", version=migration.version)


def upgrade(engine: Engine) -> list[str]:
    """Apply every pending migration. Returns the versions applied."""
    drift = changed_migrations(engine)
    if drift:
        raise RuntimeError(
            f"migration files were edited after being applied: {drift}. "
            f"Add a new migration instead of changing history."
        )

    todo = pending(engine)
    if not todo:
        logger.info("migrations_up_to_date")
        return []

    applied: list[str] = []
    for migration in todo:
        apply_migration(engine, migration)
        applied.append(migration.version)
    return applied


def status(engine: Engine) -> list[tuple[str, str, bool]]:
    """``(version, name, applied)`` for every known migration."""
    done = applied_versions(engine)
    return [(m.version, m.name, m.version in done) for m in discover()]