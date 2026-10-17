"""Recompute qualification evidence without automatically promoting strategies."""

import argparse
import json

from src.core.config import get_settings
from src.database.repositories import StrategyStatusRepository
from src.database.session import session_scope
from src.evaluation.service import evaluate_strategy
from src.strategies.registry import all_names


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=all_names())
    args = parser.parse_args(argv)
    settings = get_settings()
    reports = []
    with session_scope() as session:
        for strategy in [args.strategy] if args.strategy else all_names():
            try:
                result, ready, evidence = evaluate_strategy(session, strategy, settings)
                row = StrategyStatusRepository(session).get(strategy)
                if row is not None:
                    row.qualification = evidence
                    # Losing qualification evidence revokes permission; gaining it still needs an operator.
                    if row.qualified and not result.qualified:
                        row.qualified = False
                        row.status = "candidate"
                        row.promoted_at = None
                    row.blocking_reason = result.blocking_reason
                reports.append(
                    {
                        "strategy": strategy,
                        "qualified_by_evidence": result.qualified,
                        "paper_ready": ready,
                        "evidence": evidence,
                    }
                )
            except ValueError as exc:
                reports.append({"strategy": strategy, "error": str(exc)})
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
