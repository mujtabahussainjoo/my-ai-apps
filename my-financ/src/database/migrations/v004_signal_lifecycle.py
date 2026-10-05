"""Give signals a lifecycle, so the worker knows what is still unhandled.

Signals were write-only records. The TradingView webhook stored an alert and
stopped there, and the paper loop stored its own signals on the way to an
order. Nothing recorded the *fate* of a signal, which left two gaps:

* A signal rejected by the risk engine produced no order, so it left no trace
  at all. An operator auditing "why did nothing trade?" had no row to read.
* There was no way for a worker to find work still to do. Polling for new rows
  would re-handle every signal on every tick, and there was no marker
  distinguishing "already evaluated" from "not yet looked at".

``status`` plus ``processed_at`` records the outcome, and the partial index on
pending rows gives the worker an index-only poll. ``order_id`` links back to the
order a signal produced; it stays null for rejections, which is precisely the
case that used to be invisible.

Existing rows are marked ``executed``: every signal in the table before this
migration was written by the paper loop immediately before it submitted an
order, so none of them is pending work.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection

from src.core.logging import get_logger

logger = get_logger(__name__)

TABLE = "signals"
STATUSES = "'pending','executed','rejected','ignored'"


def upgrade(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        # SQLite cannot ADD COLUMN with a non-constant default, and the unit
        # suite builds its schema from ORM metadata, which already carries these
        # columns. Only a pre-existing SQLite file would be stale.
        logger.info("migration_sqlite_noop", reason="SQLite builds schema from ORM metadata")
        return

    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'pending'")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN processed_at TIMESTAMPTZ")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN order_id VARCHAR(36)")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN reject_reason TEXT")
    conn.exec_driver_sql(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT signal_status_valid CHECK (status IN ({STATUSES}))"
    )
    conn.exec_driver_sql(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT signal_order_id_fkey "
        f"FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL"
    )

    # Every pre-existing signal came from the paper loop on its way to an order.
    conn.exec_driver_sql(f"UPDATE {TABLE} SET status = 'executed' WHERE status = 'pending'")

    # The worker's poll: only unhandled rows, oldest first.
    conn.exec_driver_sql(
        f"CREATE INDEX ix_signals_pending ON {TABLE} (created_at) WHERE status = 'pending'"
    )
    logger.info("migration_added_signal_lifecycle", table=TABLE, statuses=STATUSES)


def downgrade(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        logger.info("migration_sqlite_noop")
        return

    conn.exec_driver_sql("DROP INDEX IF EXISTS ix_signals_pending")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS signal_order_id_fkey")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS signal_status_valid")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} DROP COLUMN reject_reason")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} DROP COLUMN order_id")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} DROP COLUMN processed_at")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} DROP COLUMN status")
    logger.info("migration_removed_signal_lifecycle")
