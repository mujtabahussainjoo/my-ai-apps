"""The paper-trading loop: fetch, analyse, risk-check, execute, manage.

One cycle is deliberately linear and auditable. Every order that leaves this loop
has passed through :class:`~src.risk.risk_engine.RiskEngine` and then through
:class:`~src.trading.executor.OrderExecutor`, which re-checks the verdict. There
is no shortcut from a signal to a fill.

The loop is safe to run with no exchange credentials, no API key, and no network:
the market-data layer can fall back to a synthetic source, which is logged loudly
because a paper result built on synthetic prices is not evidence for promotion.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.core.config import Settings, get_settings
from src.core.enums import RiskVerdict, StrategyStatus, Timeframe, TradingMode
from src.core.logging import get_logger
from src.database.repositories import (
    CandleRepository,
    OrderRepository,
    PortfolioRepository,
    RiskRepository,
    SignalRepository,
    StrategyStatusRepository,
    SystemEventRepository,
)
from src.database.repositories.trading_repo import TradeRepository
from src.market_data.normalization import CollectorRegistry
from src.risk.risk_engine import RiskEngine
from src.schemas.market import Candle, IndicatorSnapshot, Ticker
from src.schemas.order import OrderRequest
from src.schemas.signal import Signal, SignalAction
from src.strategies import registry as strategy_registry
from src.technical_analysis.feature_engine import compute_features
from src.trading.executor import ExecutionRejected, OrderExecutor
from src.trading.paper.broker import PaperBroker

logger = get_logger(__name__)


@dataclass(slots=True)
class CycleResult:
    """What one pass of the loop did, for logging and tests."""

    signals: int = 0
    orders_sent: int = 0
    orders_rejected: int = 0
    positions_closed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class PaperTradingLoop:
    """Runs the deterministic pipeline against a paper venue."""

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        risk_engine: RiskEngine | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = session
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(UTC))
        self.mode = TradingMode(self.settings.trading_mode)
        if self.mode is not TradingMode.PAPER:
            raise ValueError(
                "the paper loop runs only in paper mode; use the assisted exchange CLI for testnet/live"
            )

        self.risk = risk_engine or RiskEngine(self.settings)
        self.broker = PaperBroker(
            session,
            taker_fee_rate=self.settings.taker_fee_rate,
            slippage_rate=self.settings.slippage_rate,
            starting_cash=self.settings.starting_equity_usd,
        )
        self.executor = OrderExecutor(session, self.broker, risk_engine=self.risk)

        self.collectors = CollectorRegistry(self.settings)
        self.candles = CandleRepository(session)
        self.signals = SignalRepository(session)
        self.portfolio = PortfolioRepository(session)
        self.orders = OrderRepository(session)
        self.trades = TradeRepository(session)
        self.risk_repo = RiskRepository(session)
        self.strategies = StrategyStatusRepository(session)
        self.events = SystemEventRepository(session)
        self._synthetic_symbols = set()
        self._stopping = False
        self._loop = None

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def install_signal_handlers(self) -> None:
        """Stop cleanly on Ctrl-C so an in-flight trade is not orphaned."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: self.request_stop())
            except ValueError:  # pragma: no cover - not on the main thread
                logger.warning("signal_handler_unavailable", signal=str(sig))

    def request_stop(self) -> None:
        logger.info("paper_loop_stop_requested")
        self._stopping = True

    def run(self, cycles: int | None = None) -> list[CycleResult]:
        """Run until interrupted, or for a fixed number of cycles."""
        total = cycles if cycles is not None else self.settings.max_cycles
        limit = total if total and total > 0 else None
        results: list[CycleResult] = []
        logger.info(
            "paper_loop_started",
            mode=self.mode.value,
            symbols=self.settings.trading_symbols,
            strategies=self.settings.trading_strategies,
            interval=self.settings.poll_interval_seconds,
            cycles=limit or "unbounded",
        )
        while not self._stopping and (limit is None or len(results) < limit):
            results.append(self.run_cycle())
            if limit is None or len(results) < limit:
                self.sleep(self.settings.poll_interval_seconds)
        logger.info("paper_loop_stopped", cycles=len(results))
        return results

    # ── One cycle ────────────────────────────────────────────────────────────
    def run_cycle(self) -> CycleResult:
        from src.risk.operator_controls import sync_kill_switch

        sync_kill_switch(self.session)
        result = CycleResult()
        tickers: dict[str, Ticker] = {}

        for symbol in self.settings.trading_symbols:
            try:
                ticker = self._fetch_ticker(symbol)
            except Exception as exc:  # noqa: BLE001 - one symbol must not stop the loop
                result.errors.append(f"{symbol} ticker: {exc}")
                continue
            tickers[symbol] = ticker

        # Exits first: protecting open risk outranks finding new trades.
        result.positions_closed = self._manage_open_positions(tickers, result)

        for symbol in self.settings.trading_symbols:
            if symbol not in tickers:
                continue
            self._process_symbol(symbol, tickers[symbol], result)

        self._record_snapshot()
        self.session.commit()

        logger.info(
            "paper_cycle_complete",
            signals=result.signals,
            orders_sent=result.orders_sent,
            rejected=result.orders_rejected,
            closed=result.positions_closed,
            errors=len(result.errors),
        )
        return result

    def run_symbol(self, symbol: str) -> CycleResult:
        """Evaluate one symbol now, rather than waiting for the next tick.

        This is the path an outside trigger takes. An alert says "look at this
        market"; it does not say what to buy, at what price, or with what stop.
        Those come from the strategies, here, against live indicators - so the
        order that results is traceable to deterministic reasoning rather than
        to whoever configured the alert.
        """
        result = CycleResult()
        try:
            ticker = self._fetch_ticker(symbol)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{symbol} ticker: {exc}")
            return result

        result.positions_closed = self._manage_open_positions({symbol: ticker}, result)
        self._process_symbol(symbol, ticker, result)
        self._record_snapshot()
        self.session.commit()
        logger.info(
            "symbol_evaluation_complete",
            symbol=symbol,
            signals=result.signals,
            orders_sent=result.orders_sent,
            rejected=result.orders_rejected,
        )
        return result

    def _process_symbol(self, symbol: str, ticker: Ticker, result: CycleResult) -> None:
        """Ask every qualified strategy for a view, and act on what they say."""
        if symbol in self._synthetic_symbols:
            result.errors.append(f"{symbol}: synthetic quote excluded from trading evidence")
            return
        try:
            candles, indicators = self._load_analysis_data(symbol)
            if candles is None or indicators is None:
                return
            for signal in strategy_registry.evaluate_all(
                symbol,
                Timeframe(self.settings.trading_timeframe),
                candles,
                indicators,
                strategies=self._qualified_strategies(symbol),
            ):
                result.signals += 1
                self._handle_signal(signal, ticker, indicators, result)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{symbol} cycle: {exc}")
            logger.exception("paper_cycle_failed", symbol=symbol)
            # The session is poisoned after any flush-time failure; without
            # a rollback every later symbol in this cycle dies with
            # PendingRollbackError instead of its own real error.
            self.session.rollback()

    # ── Data ─────────────────────────────────────────────────────────────────
    def _fetch_ticker(self, symbol: str) -> Ticker:
        collector = self.collectors.get()
        self._synthetic_symbols.discard(symbol)
        try:
            return self._run_async(collector.fetch_ticker(symbol))
        except Exception as exc:  # noqa: BLE001
            if not self.settings.market_data_allow_synthetic:
                raise
            logger.warning(
                "market_data_fallback_synthetic",
                symbol=symbol,
                error=str(exc),
                note="paper results from synthetic prices are not promotion evidence",
            )
            self._synthetic_symbols.add(symbol)
            return self._run_async(self.collectors.synthetic().fetch_ticker(symbol))

    def _load_analysis_data(self, symbol: str) -> tuple[list[Candle] | None, IndicatorSnapshot | None]:
        """Prefer stored candles; fall back to the exchange when history is thin."""
        timeframe = Timeframe(self.settings.trading_timeframe)
        # get_range returns oldest-first, which is the only order indicators
        # may be computed in; ascending=False with a limit gives the latest bars.
        candles = self.candles.get_range(symbol, timeframe, limit=300, ascending=False)
        candles.reverse()

        if len(candles) < 120:
            collector = self.collectors.get()
            try:
                fresh = self._run_async(collector.fetch_historical(symbol, timeframe, max_candles=300))
                if fresh:
                    self.candles.upsert_many(fresh)
                    candles = sorted(fresh, key=lambda c: c.timestamp)
            except Exception as exc:  # noqa: BLE001
                logger.warning("historical_fetch_failed", symbol=symbol, error=str(exc))

        now = self.clock()
        candles = [c for c in candles if c.timestamp.timestamp() + timeframe.seconds <= now.timestamp()]
        if len(candles) < 60:
            logger.info("insufficient_history", symbol=symbol, candles=len(candles))
            return (candles or None), None
        try:
            return candles, compute_features(candles, timeframe=self.settings.trading_timeframe)
        except Exception as exc:  # noqa: BLE001 - cold toolkit is not an error
            logger.info("indicators_unavailable", symbol=symbol, error=str(exc))
            return candles, None

    def _ensure_loop(self):
        """One event loop for the whole trading loop.

        ``asyncio.run`` per call would build and tear down a loop each time, and
        the collectors hold a pooled httpx client bound to the first one. After
        the first call closed its loop, every later fetch failed with
        "Event loop is closed".
        """
        import asyncio

        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def _run_async(self, coro):
        """Run a collector coroutine on the loop's own event loop."""
        return self._ensure_loop().run_until_complete(coro)

    def close(self) -> None:
        """Release the event loop and any pooled HTTP connections."""
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.run_until_complete(self._shutdown_async())
            except Exception as exc:  # noqa: BLE001 - best effort on the way out
                logger.warning("collector_shutdown_failed", error=type(exc).__name__)
            self._loop.close()
            self._loop = None

    async def _shutdown_async(self) -> None:
        collectors = list(getattr(self.collectors, "_collectors", {}).values())
        for collector in collectors:
            client = getattr(collector, "client", None)
            close = getattr(client, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("collector_shutdown_failed", error=type(exc).__name__)

    # ── Strategy gating ──────────────────────────────────────────────────────
    def _qualified_strategies(self, symbol: str) -> list[str]:
        """Only strategies cleared to trade, per stored status.

        The risk engine re-checks qualification, so this is an optimisation that
        also keeps the audit trail short - not the enforcement point.
        """
        return [
            name
            for name in self.settings.trading_strategies
            if self.strategy_status(name)
            in (StrategyStatus.QUALIFIED, StrategyStatus.BACKTEST_PASSED, StrategyStatus.PAPER_TESTING)
        ]

    def strategy_status(self, name: str) -> StrategyStatus:
        """Resolve a stored status to the enum the risk engine expects.

        The ORM column is a plain string, and the engine compares against enum
        members, so an unconverted value is not merely untidy: it fails the
        qualification check instead of answering it.
        """
        row = self.strategies.get(name)
        if row is None:
            return StrategyStatus.CANDIDATE
        try:
            return StrategyStatus(row.status)
        except ValueError:
            logger.warning("unknown_strategy_status", strategy=name, status=row.status)
            return StrategyStatus.CANDIDATE

    # ── Signal handling ──────────────────────────────────────────────────────
    def _handle_signal(
        self,
        signal: Signal,
        ticker: Ticker,
        indicators: IndicatorSnapshot,
        result: CycleResult,
    ) -> None:
        existing = next(
            (pos for pos in self.portfolio.get_positions(self.mode.value) if pos.symbol == signal.symbol),
            None,
        )
        if existing is not None and signal.action == SignalAction.BUY:
            # No pyramiding. A strategy that is still bullish on the next poll
            # would otherwise re-buy every cycle, and the per-order cap would
            # quietly turn a single idea into an ever-larger average-up.
            result.orders_rejected += 1
            logger.info(
                "entry_skipped_position_exists",
                symbol=signal.symbol,
                strategy=signal.strategy,
                position_quantity=round(existing.quantity, 8),
            )
            return

        signal_id = self.signals.record(signal)
        request = self._request_from_signal(signal, indicators, signal_id)
        portfolio = self.portfolio.build_snapshot(self.mode.value)

        agent_approved = True
        if self.settings.llm_enabled:
            from src.agents.supervisor.agent import Supervisor
            from src.news.collector import NewsCollector

            try:
                news = NewsCollector(self.settings).fetch() if self.settings.news_feed_urls else []
                reviewer = Supervisor(self.settings)
                review = reviewer.analyse(
                    signal, ticker=ticker, portfolio=portfolio, news=news, session=self.session
                )
                agent_approved = reviewer.approved(review)
            except Exception:
                agent_approved = False
        assessment = self.risk.assess(
            request,
            portfolio,
            ticker=ticker,
            signal=signal,
            strategy_status=self.strategy_status(signal.strategy),
            agent_approved=agent_approved,
            atr=indicators.atr,
        )
        if not assessment.allowed:
            result.orders_rejected += 1
            self.signals.mark_rejected(signal_id, "; ".join(assessment.reasons))
            self.executor._audit_rejection(request, assessment, portfolio)
            logger.info(
                "signal_rejected",
                symbol=signal.symbol,
                strategy=signal.strategy,
                verdict=assessment.verdict.value,
                reasons=assessment.reasons,
            )
            return

        try:
            outcome = self.executor.execute(request, assessment, ticker=ticker, portfolio=portfolio)
        except ExecutionRejected as exc:
            result.orders_rejected += 1
            self.signals.mark_rejected(signal_id, str(exc))
            logger.info("execution_rejected", symbol=signal.symbol, reason=str(exc))
            return

        self.signals.mark_executed(signal_id, outcome.order_id)
        result.orders_sent += 1
        logger.info(
            "signal_executed",
            symbol=signal.symbol,
            strategy=signal.strategy,
            status=outcome.status,
            quantity=assessment.approved_quantity,
            detail=outcome.detail,
        )

    def _request_from_signal(
        self, signal: Signal, indicators: IndicatorSnapshot, signal_id: str
    ) -> OrderRequest:
        """Translate a signal into an order request the risk engine can judge."""
        from src.core.enums import OrderSide, OrderType, SignalAction

        side = OrderSide.BUY if signal.action is SignalAction.BUY else OrderSide.SELL
        return OrderRequest(
            symbol=signal.symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=self._size_for(signal, indicators),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy=signal.strategy,
            signal_id=signal_id,
            mode=self.mode,
        )

    def _size_for(self, signal: Signal, indicators: IndicatorSnapshot) -> float:
        """ATR-based sizing; the risk engine still has the final say on quantity."""
        atr = indicators.atr
        if not atr or atr <= 0 or signal.stop_loss is None:
            return 0.0
        risk_budget = self.settings.starting_equity_usd * self.settings.risk_max_risk_per_trade_pct / 100
        stop_distance = abs(signal.entry - signal.stop_loss)
        if stop_distance <= 0:
            return 0.0
        return round(risk_budget / stop_distance, 8)

    # ── Position management ──────────────────────────────────────────────────
    def _manage_open_positions(self, tickers: dict[str, Ticker], result: CycleResult) -> int:
        """Honour stops and targets before anything else happens."""
        closed = 0
        for position in self.portfolio.get_positions(self.mode.value):
            if position.symbol in self._synthetic_symbols:
                continue
            ticker = tickers.get(position.symbol)
            if ticker is None:
                continue
            self.portfolio.upsert_position(position.model_copy(update={"current_price": ticker.last}))

            reason = self._exit_trigger(position, ticker)
            if reason is None:
                continue
            try:
                self.executor.close_position(
                    position.symbol,
                    ticker.bid or ticker.last,
                    reason=reason,
                    ticker=ticker,
                )
                closed += 1
            except ExecutionRejected as exc:
                result.errors.append(f"exit {position.symbol}: {exc}")
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"exit {position.symbol}: {exc}")
                logger.exception("position_exit_failed", symbol=position.symbol)
        return closed

    @staticmethod
    def _exit_trigger(position, ticker: Ticker) -> str | None:
        """Which protective level the market has reached, if any.

        A long's stop is hit by the *bid* reaching it, because that is the price
        the position could actually be sold at.
        """
        bid = ticker.bid or ticker.last
        ask = ticker.ask or ticker.last
        if position.side.value == "buy":
            if position.stop_loss and bid <= position.stop_loss:
                return "stop_loss"
            if position.take_profit and bid >= position.take_profit:
                return "take_profit"
        else:
            if position.stop_loss and ask >= position.stop_loss:
                return "stop_loss"
            if position.take_profit and ask <= position.take_profit:
                return "take_profit"
        return None

    # ── Bookkeeping ──────────────────────────────────────────────────────────
    def _record_snapshot(self) -> None:
        self.portfolio.record_snapshot(self.portfolio.build_snapshot(self.mode.value))

    def summary(self) -> dict[str, object]:
        """Current account state, for the CLI and for `make paper` output."""
        snapshot = self.portfolio.build_snapshot(self.mode.value)
        return {
            "mode": self.mode.value,
            "equity_usd": round(snapshot.equity_usd, 2),
            "cash_usd": round(snapshot.cash_usd, 2),
            "positions": len(snapshot.positions),
            "exposure_usd": round(snapshot.total_exposure_usd, 2),
            "unrealized_pnl_usd": round(snapshot.unrealized_pnl_usd, 2),
            "realized_pnl_usd": round(snapshot.realized_pnl_usd, 2),
            "open_orders": len(self.orders.open_orders(self.mode.value)),
            "open_trades": len(self.trades.open_trades(self.mode.value)),
            "closed_trades": len(self.trades.closed_trades(self.mode.value)),
            "verdict_last": RiskVerdict.APPROVED.value,
            "as_of": snapshot.as_of.isoformat(),
        }


__all__ = ["CycleResult", "PaperTradingLoop"]
