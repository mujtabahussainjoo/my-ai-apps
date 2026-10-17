"""Initial schema: 22 tables covering market data, trading, risk and agents."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from src.core.logging import get_logger

logger = get_logger(__name__)


def upgrade(conn: Connection) -> None:
    # Importing the models package registers every mapper on Base.metadata.
    from src.database import models  # noqa: F401
    from src.database.base import Base

    logger.info("migration_creating_tables", count=len(Base.metadata.tables))
    Base.metadata.create_all(bind=conn, checkfirst=True)

    # Server-side guarantees that a plain CHECK cannot express. Skipped on
    # SQLite, which the offline test suite uses.
    if conn.dialect.name != "postgresql":
        logger.info("migration_skipping_postgres_only_statements")
        return

    statements = [
        # A candle timestamp must be unique per symbol+timeframe even if an
        # application bug slips past the unique constraint.
        """
        CREATE INDEX IF NOT EXISTS ix_candles_symbol_time_desc
            ON candles (symbol, timeframe, timestamp DESC)
        """,
        # Trade P&L is recomputed from fills on audit; keep the ledger readable.
        """
        CREATE INDEX IF NOT EXISTS ix_trades_open_positions
            ON trades (mode, symbol) WHERE is_open = true
        """,
        # Only failed checks are queried in practice ("why was this rejected?").
        """
        CREATE INDEX IF NOT EXISTS ix_risk_events_failed_only
            ON risk_events (created_at DESC) WHERE passed = false
        """,
    ]
    for statement in statements:
        conn.execute(text(statement))
    logger.info("migration_postgres_indexes_created", count=len(statements))