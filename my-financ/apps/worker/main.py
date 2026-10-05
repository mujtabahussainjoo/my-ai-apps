"""Background worker.

Two kinds of work, on one schedule:

* **Strategy cycles** - the paper loop asks every qualified strategy for a view
  and sends anything it likes to the risk engine.
* **Signal processing** - alerts that arrived from outside (a TradingView
  webhook) are drained from the queue and put through the same risk gate.

Both share the paper loop's broker, risk engine and HTTP connections. Splitting
them across processes would mean two views of the same balances and two sets of
pooled collectors for no benefit; the work is seconds long, not CPU-bound.

The worker is a supervisor, not a strategy. It decides nothing about markets,
and it has no route to an order that does not pass through ``RiskEngine``.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass

from src.core.config import Settings, get_settings
from src.core.logging import configure_logging, get_logger
from src.database.repositories import SystemEventRepository
from src.database.session import session_scope
from src.trading.paper_loop import PaperTradingLoop
from src.trading.signal_processor import SignalProcessor, signal_processor_from_loop

logger = get_logger(__name__)

DEFAULT_INTERVAL = 60.0


@dataclass
class TickResult:
    """One pass of the worker."""

    strategies_ok: bool
    signals_processed: int
    signals_executed: int
    signals_rejected: int
    signals_deferred: int

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TickResult(strategies_ok={self.strategies_ok}, "
            f"signals={self.signals_processed}, executed={self.signals_executed}, "
            f"rejected={self.signals_rejected}, deferred={self.signals_deferred})"
        )


class Worker:
    """Runs the schedule until asked to stop."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        interval: float = DEFAULT_INTERVAL,
        run_strategies: bool = True,
        run_signals: bool = True,
        sleep=time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self.interval = interval
        self.run_strategies = run_strategies
        self.run_signals = run_signals
        self.sleep = sleep
        self._stopping = False
        self._loop: PaperTradingLoop | None = None
        self._processor: SignalProcessor | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    def install_signal_handlers(self) -> None:
        """Stop cleanly on SIGINT/SIGTERM so the loop can close its pool."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_stop)

    def _handle_stop(self, signum, _frame) -> None:
        logger.info("worker_stop_requested", signal=signum)
        self._stopping = True

    def run(self, cycles: int | None = None) -> list[TickResult]:
        """Run ``cycles`` passes, or until stopped when ``cycles`` is None."""
        self.install_signal_handlers()
        results: list[TickResult] = []
        with session_scope() as session:
            self._loop = PaperTradingLoop(session, self.settings)
            self._processor = signal_processor_from_loop(self._loop)
            logger.info(
                "worker_started",
                mode=self.settings.trading_mode,
                interval=self.interval,
                cycles=cycles,
                strategies=self.run_strategies,
                signals=self.run_signals,
            )
            try:
                while not self._stopping and (cycles is None or len(results) < cycles):
                    results.append(self.tick())
                    if cycles is not None and len(results) >= cycles:
                        break
                    if cycles is None and not self._stopping:
                        self.sleep(self.interval)
            finally:
                self._loop.close()
                self._loop = None
                self._processor = None
        logger.info("worker_stopped", ticks=len(results))
        return results

    # ── one pass ─────────────────────────────────────────────────────────────

    def tick(self) -> TickResult:
        """Run both halves of the schedule once.

        A failure in either half must not stop the other from running, so each
        is isolated: a strategy that raises does not strand queued signals.
        """
        assert self._loop is not None and self._processor is not None
        strategies_ok = True

        if self.run_strategies:
            try:
                cycle = self._loop.run_cycle()
                logger.info(
                    "strategy_cycle",
                    ok=cycle.ok,
                    orders_sent=cycle.orders_sent,
                    orders_rejected=cycle.orders_rejected,
                    errors=cycle.errors,
                )
            except Exception as exc:  # noqa: BLE001 - one bad cycle must not kill the worker
                strategies_ok = False
                logger.error("strategy_cycle_failed", error=str(exc), error_type=type(exc).__name__)
                self._note("worker", "strategy_cycle_failed", "strategy cycle failed", str(exc))

        processed = executed = rejected = deferred = 0
        if self.run_signals:
            try:
                outcome = self._processor.process_pending()
                processed = outcome.processed
                executed = outcome.executed
                rejected = outcome.rejected
                deferred = outcome.deferred
            except Exception as exc:  # noqa: BLE001 - see above
                logger.error("signal_processing_failed", error=str(exc), error_type=type(exc).__name__)
                self._note(
                    "worker", "signal_processing_failed", "signal processing failed", str(exc)
                )

        return TickResult(
            strategies_ok=strategies_ok,
            signals_processed=processed,
            signals_executed=executed,
            signals_rejected=rejected,
            signals_deferred=deferred,
        )

    def _note(self, component: str, event: str, message: str, detail: str | None = None) -> None:
        """Write an audit row for a failure the worker survived."""
        try:
            with session_scope() as session:
                SystemEventRepository(session).log(
                    component=component,
                    event=event,
                    message=message,
                    level="error",
                    context={"detail": detail} if detail else None,
                )
        except Exception as exc:  # noqa: BLE001 - never fail because of the audit note
            logger.warning("event_not_recorded", error=str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.worker.main",
        description="Drain queued signals and run strategy cycles.",
    )
    parser.add_argument(
        "--once", action="store_true", help="run a single pass and exit"
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="stop after this many passes (default: run until interrupted)",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL, help="seconds between passes"
    )
    parser.add_argument("--no-strategies", action="store_true", help="skip strategy cycles")
    parser.add_argument("--no-signals", action="store_true", help="skip queued signals")
    args = parser.parse_args(argv)

    configure_logging()
    settings = get_settings()
    if settings.trading_mode == "backtest":
        parser.error("the worker does not run in backtest mode")

    worker = Worker(
        settings,
        interval=args.interval,
        run_strategies=not args.no_strategies,
        run_signals=not args.no_signals,
    )
    cycles = 1 if args.once else args.cycles
    results = worker.run(cycles=cycles)

    totals = {
        "ticks": len(results),
        "executed": sum(r.signals_executed for r in results),
        "rejected": sum(r.signals_rejected for r in results),
        "deferred": sum(r.signals_deferred for r in results),
    }
    print(f"worker finished: {totals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
