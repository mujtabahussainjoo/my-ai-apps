"""Widen ``risk_events.unit``.

The column was declared ``VARCHAR(16)`` while the risk engine writes unit
labels like ``"percent of equity"`` (17 characters). Every assessment that
produced one of those checks raised::

    StringDataRightTruncation: value too long for type character varying(16)

which aborted the whole ``risk_events`` insert - so a *successful* assessment
could not be recorded at all. The audit trail failing on a valid label is not
an acceptable trade-off; the column is widened instead of truncating the label,
because a truncated unit is silently wrong to whoever reads it later.

``VARCHAR(32)`` comfortably covers the current labels (``usd``, ``percent``,
``percent of equity``, ``seconds``, ``trades``) with room to grow.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection

from src.core.logging import get_logger

logger = get_logger(__name__)

COLUMN = "unit"
NEW_TYPE = "VARCHAR(32)"


def upgrade(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        # SQLite has no ALTER COLUMN TYPE. The unit suite builds its schema from
        # ORM metadata, which already carries the wider column; only a
        # pre-existing SQLite file would be stale, and those are throwaway.
        logger.info("migration_sqlite_noop", reason="SQLite cannot alter column types")
        return

    conn.exec_driver_sql(f"ALTER TABLE risk_events ALTER COLUMN {COLUMN} TYPE {NEW_TYPE}")
    logger.info("migration_widened_risk_events_unit", type=NEW_TYPE)


def downgrade(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        logger.info("migration_sqlite_noop")
        return
    conn.exec_driver_sql(f"ALTER TABLE risk_events ALTER COLUMN {COLUMN} TYPE VARCHAR(16)")
    logger.info("migration_narrowed_risk_events_unit")
