"""Run the paper-trading loop from the command line.

    make paper                       # honour TRADING_MODE and .env
    make paper CYCLES=10 INTERVAL=5  # short bounded demonstration
    python -m scripts.start_paper_trading --cycles 10

Every order this can produce is gated by the hard risk engine, so running it
without credentials, without an API key, and against synthetic prices is safe.
"""

from __future__ import annotations

import argparse
import sys

from src.core.config import get_settings
from src.core.logging import configure_logging, get_logger
from src.database.migrations import upgrade
from src.database.seed import ensure_reference_data
from src.database.session import build_engine, session_scope
from src.trading.paper_loop import PaperTradingLoop

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the paper-trading loop")
    parser.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="number of decision cycles to run (default: until interrupted)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="seconds between cycles (default: from settings)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="print the current account state and exit without trading",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging()
    logger.info(
        "paper_trading_starting",
        mode=settings.trading_mode,
        symbols=settings.trading_symbols,
        live_enabled=settings.live_trading_enabled,
    )

    try:
        engine = build_engine()
    except Exception as exc:  # noqa: BLE001
        print(f"cannot reach the database: {exc}", file=sys.stderr)
        print("run 'make up' first", file=sys.stderr)
        return 1

    try:
        upgrade(engine)
        with session_scope() as session:
            ensure_reference_data(session, settings)
    except Exception as exc:  # noqa: BLE001
        print(f"startup failed: {exc}", file=sys.stderr)
        return 1

    if args.interval is not None:
        settings.poll_interval_seconds = max(1, int(args.interval))

    with session_scope() as session:
        loop = PaperTradingLoop(session, settings)
        if args.summary_only:
            print(_format(loop.summary()))
            return 0

        loop.install_signal_handlers()
        cycles = args.cycles if args.cycles is not None else settings.max_cycles
        try:
            results = loop.run(cycles=cycles or None)
        except KeyboardInterrupt:
            logger.info("paper_trading_interrupted")
            results = []

        summary = loop.summary()

    print(_format(summary))
    if results:
        sent = sum(r.orders_sent for r in results)
        rejected = sum(r.orders_rejected for r in results)
        closed = sum(r.positions_closed for r in results)
        errors = sum(len(r.errors) for r in results)
        print(
            f"\n{len(results)} cycle(s): {sent} order(s) sent, "
            f"{rejected} rejected, {closed} position(s) closed, {errors} error(s)"
        )
    return 0 if not any(not r.ok for r in results) else 1


def _format(summary: dict[str, object]) -> str:
    label = {
        "equity_usd": "equity",
        "cash_usd": "cash",
        "positions": "positions",
        "exposure_usd": "exposure",
        "unrealized_pnl_usd": "unrealized P&L",
        "realized_pnl_usd": "realized P&L",
        "open_orders": "open orders",
        "open_trades": "open trades",
        "closed_trades": "closed trades",
    }
    lines = ["", f"  paper trading account ({summary['mode']})", ""]
    for key, text in label.items():
        if key in summary:
            lines.append(f"  {text:<16} {summary[key]}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
