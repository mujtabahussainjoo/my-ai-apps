"""Claim queued signals before side effects; uncertain attempts stay quarantined."""

from sqlalchemy.engine import Connection


def upgrade(conn: Connection) -> None:
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql("ALTER TABLE signals DROP CONSTRAINT IF EXISTS signal_status_valid")
        conn.exec_driver_sql("ALTER TABLE signals DROP CONSTRAINT IF EXISTS ck_signals_signal_status_valid")
        conn.exec_driver_sql(
            "ALTER TABLE signals ADD CONSTRAINT signal_status_valid CHECK (status IN ('pending','processing','executed','rejected','ignored'))"
        )


def downgrade(conn: Connection) -> None:
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql(
            "UPDATE signals SET status='ignored', reject_reason='Interrupted processing requires manual reconciliation' WHERE status='processing'"
        )
        conn.exec_driver_sql("ALTER TABLE signals DROP CONSTRAINT IF EXISTS signal_status_valid")
        conn.exec_driver_sql("ALTER TABLE signals DROP CONSTRAINT IF EXISTS ck_signals_signal_status_valid")
        conn.exec_driver_sql(
            "ALTER TABLE signals ADD CONSTRAINT signal_status_valid CHECK (status IN ('pending','executed','rejected','ignored'))"
        )
