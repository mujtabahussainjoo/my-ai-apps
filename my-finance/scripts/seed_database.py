"""Seed reference data: strategies and the starting paper balance.

Idempotent, and deliberately not a shortcut around the promotion gate. Every
strategy is created CANDIDATE, so seeding can never make an unqualified strategy
tradeable.

    make seed
    make seed QUALIFY=momentum      # requires passing backtest/OOS/paper evidence
"""

from __future__ import annotations

import argparse
import sys

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.database.migrations import upgrade
from src.database.seed import DEFAULT_STRATEGIES, ensure_reference_data, set_qualified
from src.database.session import build_engine, session_scope

logger = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed reference data")
    parser.add_argument(
        "--qualify",
        default=None,
        help=f"strategy to mark QUALIFIED ({'|'.join(DEFAULT_STRATEGIES)})",
    )
    parser.add_argument(
        "--revoke",
        default=None,
        help="strategy to return to CANDIDATE",
    )
    parser.add_argument(
        "--reason",
        default="operator reviewed evidence",
        help="justification recorded alongside a qualification change",
    )
    args = parser.parse_args(argv)

    configure_logging()
    settings = get_settings()
    try:
        engine = build_engine()
        upgrade(engine)
        with session_scope() as session:
            created = ensure_reference_data(session, settings)
            if args.qualify:
                from src.evaluation.service import evaluate_strategy

                report, _, evidence = evaluate_strategy(session, args.qualify, settings)
                if not report.qualified:
                    raise ValueError(report.blocking_reason)
                set_qualified(
                    session, args.qualify, qualified=True, reason=args.reason, qualification=evidence
                )
            if args.revoke:
                set_qualified(session, args.revoke, qualified=False, reason=args.reason)
    except Exception as exc:  # noqa: BLE001
        print(f"seeding failed: {exc}", file=sys.stderr)
        print("run 'make up' first", file=sys.stderr)
        return 1

    print(
        f"seeded {created['strategies']} strategy row(s), "
        f"{created['balances']} balance row(s); all strategies start CANDIDATE"
    )
    if args.qualify:
        print(f"qualified {args.qualify} ({args.reason})")
    if args.revoke:
        print(f"revoked {args.revoke}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
