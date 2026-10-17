"""Remove duplicate historical P&L constraints created under two names."""

from sqlalchemy.engine import Connection


def upgrade(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        return
    for name in ("pnl_is_net_of_fees", "ck_trades_pnl_is_net_of_fees"):
        conn.exec_driver_sql(f"ALTER TABLE trades DROP CONSTRAINT IF EXISTS {name}")
    conn.exec_driver_sql(
        "ALTER TABLE trades ADD CONSTRAINT ck_trades_pnl_is_net_of_fees CHECK "
        "(abs(round(gross_pnl_usd - fees_usd, 6) - round(pnl_usd, 6)) <= 0.000001)"
    )
