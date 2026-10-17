"""Propose or explicitly execute a human-approved testnet/live order."""

import argparse
import json

from src.core.config import get_settings
from src.database.session import session_scope
from src.trading.assisted import AssistedTrading


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal")
    parser.add_argument("--quantity", type=float)
    parser.add_argument("--limit-price", type=float)
    parser.add_argument("--execute", metavar="APPROVAL_ID")
    args = parser.parse_args(argv)
    if not args.execute and not (args.signal and args.quantity and args.limit_price):
        parser.error("provide --signal, --quantity, --limit-price to propose, or --execute APPROVAL_ID")
    settings = get_settings()
    with session_scope() as session:
        service = AssistedTrading(session, settings)
        result = (
            service.execute(args.execute)
            if args.execute
            else service.propose(args.signal, args.quantity, args.limit_price)
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
