"""Align stored strategy stages with qualification and paper-forward testing."""

from sqlalchemy.engine import Connection


def upgrade(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        return  # SQLite development schemas are created from current metadata.
    conn.exec_driver_sql("ALTER TABLE strategy_status DROP CONSTRAINT IF EXISTS status_valid")
    conn.exec_driver_sql(
        "ALTER TABLE strategy_status DROP CONSTRAINT IF EXISTS ck_strategy_status_status_valid"
    )
    conn.exec_driver_sql(
        "ALTER TABLE strategy_status ADD CONSTRAINT status_valid CHECK (status IN ('candidate','backtesting','backtest_passed','paper_testing','paper','qualified','rejected','suspended','retired'))"
    )


def downgrade(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        return
    conn.exec_driver_sql(
        "UPDATE strategy_status SET status = 'candidate', qualified = false WHERE status IN ('backtest_passed','paper_testing','rejected')"
    )
    conn.exec_driver_sql("ALTER TABLE strategy_status DROP CONSTRAINT IF EXISTS status_valid")
    conn.exec_driver_sql(
        "ALTER TABLE strategy_status DROP CONSTRAINT IF EXISTS ck_strategy_status_status_valid"
    )
    conn.exec_driver_sql(
        "ALTER TABLE strategy_status ADD CONSTRAINT status_valid CHECK (status IN ('candidate','backtesting','paper','qualified','suspended','retired'))"
    )
