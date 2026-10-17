"""Relax the trade P&L check constraint to a tolerance.

The original constraint was::

    round(gross_pnl_usd - fees_usd, 6) = round(pnl_usd, 6)

That holds exactly on PostgreSQL, where both columns are true ``NUMERIC``. On
SQLite ``NUMERIC`` is ``REAL``, so ``gross - fees`` is evaluated in binary
floating point and can land one ulp away from the stored ``pnl_usd``::

    sqlite> select round(-1.1 - 0.2000005, 6) = round(-1.3000005, 6);
    0                      -- -1.300001 vs -1.3

A correct ledger was therefore rejected. The replacement keeps the guarantee -
net P&L equals gross minus fees - within a millionth of a dollar, which is orders
of magnitude below any fee actually charged.
"""

from __future__ import annotations

from sqlalchemy.engine import Connection

from src.core.logging import get_logger

logger = get_logger(__name__)

OLD_CONSTRAINT = "pnl_is_net_of_fees"
NEW_EXPRESSION = (
    "abs(round(gross_pnl_usd - fees_usd, 6) - round(pnl_usd, 6)) <= 0.000001"
)


def upgrade(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        # SQLite cannot add or drop CHECK constraints. The unit suite builds its
        # schema from the ORM metadata, which already carries the new expression,
        # so only long-lived SQLite files would keep the stricter form. Those are
        # throwaway development databases: recreate them.
        logger.info(
            "migration_sqlite_noop",
            reason="SQLite cannot alter CHECK constraints; recreate the file",
        )
        return

    conn.exec_driver_sql(f"ALTER TABLE trades DROP CONSTRAINT IF EXISTS {OLD_CONSTRAINT}")
    conn.exec_driver_sql(
        f"ALTER TABLE trades ADD CONSTRAINT {OLD_CONSTRAINT} CHECK ({NEW_EXPRESSION})"
    )
    logger.info("migration_relaxed_pnl_constraint")


def downgrade(conn: Connection) -> None:
    """Restore exact equality.

    This reintroduces the SQLite false rejection described above, so it is only
    meaningful on PostgreSQL.
    """
    if conn.dialect.name != "postgresql":
        logger.info("migration_sqlite_noop")
        return
    conn.exec_driver_sql(f"ALTER TABLE trades DROP CONSTRAINT IF EXISTS {OLD_CONSTRAINT}")
    conn.exec_driver_sql(
        f"ALTER TABLE trades ADD CONSTRAINT {OLD_CONSTRAINT} CHECK "
        "(round(gross_pnl_usd - fees_usd, 6) = round(pnl_usd, 6))"
    )
    logger.info("migration_restored_pnl_constraint")
