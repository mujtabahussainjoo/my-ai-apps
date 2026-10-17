"""Read venue orders and balances into the ledger; never place an order."""

from src.core.config import get_settings
from src.database.session import session_scope
from src.trading.live.broker import ExchangeBroker
from src.trading.live.reconciliation import reconcile_orders


def main():
    broker = ExchangeBroker.from_settings(get_settings())
    with session_scope() as session:
        count = reconcile_orders(session, broker)
    print(f"Reconciled {count} exchange orders and current holdings")


if __name__ == "__main__":
    main()
