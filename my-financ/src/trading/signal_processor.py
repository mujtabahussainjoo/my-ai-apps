"""Turning recorded signals into orders, under the same rules as everything else.

The TradingView webhook deliberately stops at "recorded". Something has to
consume those rows eventually, and this is that something. It exists as a
separate class rather than a worker-loop function for one reason: the
conversation that turns a third party's message into a trade is exactly the
conversation that must not have shortcuts in it.

Three properties are enforced here, and each has a test:

* **No bypass.** Every signal goes through ``RiskEngine.assess`` and then
  ``OrderExecutor.execute``. There is no path in this module that writes an
  order. If the strategy is ``CANDIDATE`` the assessment fails closed, so an
  alert naming an unqualified strategy is recorded and rejected - never traded.
* **Untrusted levels.** ``stop_loss`` and ``take_profit`` arrive from whoever
  configured the TradingView alert. Sizing is derived from stop distance, so a
  sender claiming a 0.1% stop could ask for a position twenty times larger
  than intended. The sender's levels are therefore advisory: the protective
  stop is recomputed from ATR and a disagreement is recorded on the signal.
* **Exactly once.** A settled signal leaves ``pending``, so re-running the
  worker - or running two of them - does not trade the same alert twice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from src.core.enums import OrderSide, OrderType, SignalAction, StrategyStatus, TradingMode
from src.core.logging import get_logger
from src.schemas.base import Base, Field, utcnow
from src.schemas.market import Ticker
from src.schemas.order import OrderRequest
from src.schemas.signal import Signal, Timeframe
from src.trading.executor import ExecutionRejected, OrderExecutor, describe_rejection

logger = get_logger(__name__)

#: A seller's stop closer than this multiple of ATR is not a stop, it is a typo
#: or an attempt to inflate size. Anything tighter is discarded in favour of
#: the ATR-derived level.
MIN_STOP_ATR_MULTIPLE = 0.25

#: How far an alert's price may sit from the live price before it is called out.
#: Beyond this the alert is describing a market that has already moved.
STALE_ENTRY_TOLERANCE_PCT = 0.5


def _join(*parts: str | None) -> str | None:
    """Concatenate the adjustment notes that actually exist."""
    kept = [p for p in parts if p]
    return "; ".join(kept) if kept else None


class MarketQuote(Base):
    """A price and the volatility to size against.

    Both are needed together: ATR decides where the protective stop goes and
    therefore how large the position may be, so a quote without volatility is
    not enough to act on.
    """

    symbol: str
    price: float
    atr: float | None = None
    timestamp: datetime = Field(default_factory=utcnow)

    @property
    def ticker(self) -> Ticker:
        """The exchange view of this quote, for the risk engine and executor."""
        return Ticker(
            symbol=self.symbol,
            last=self.price,
            bid=self.price,
            ask=self.price,
            timestamp=self.timestamp,
        )


class QuoteProvider(Protocol):
    """Supplies live prices and derived volatility. An interface, so tests need no network."""

    def quote(self, symbol: str, timeframe: Timeframe) -> MarketQuote | None: ...


class CollectorQuoteProvider:
    """Fetches tickers from the market collector and ATR from stored candles.

    A collector holds an ``httpx`` client bound to the loop that created it, so
    reusing one from the API or paper loop would corrupt it. This provider owns
    a loop for its lifetime and closes both together.

    ATR comes from indicators computed over stored candles, exactly as the paper
    loop derives it - it is not a field the exchange quotes.
    """

    def __init__(
        self,
        fetch_ticker: "Callable[[str], Ticker]",
        candles,
        *,
        lookback: int = 200,
        timeframe: Timeframe = Timeframe.H1,
    ) -> None:
        self._fetch = fetch_ticker
        self._candles = candles
        self._lookback = lookback
        self._timeframe = timeframe

    def quote(self, symbol: str, timeframe: Timeframe | None = None) -> MarketQuote | None:
        tf = timeframe or self._timeframe
        ticker = self._fetch(symbol)
        price = ticker.mid if (ticker.bid and ticker.ask) else ticker.last
        return MarketQuote(
            symbol=symbol,
            price=float(price),
            atr=self._atr(symbol, tf),
            timestamp=ticker.timestamp,
        )

    def _atr(self, symbol: str, timeframe: Timeframe) -> float | None:
        """ATR from the stored series, or None if there is not enough history.

        Returning None is deliberate: a half-warmed-up indicator set must not
        produce a stop distance, and the caller refuses to trade without one.
        """
        from src.technical_analysis.feature_engine import (
            InsufficientDataError,
            compute_features,
        )

        rows = self._candles.get_range(
            symbol, timeframe, limit=self._lookback, ascending=False
        )
        rows.reverse()
        try:
            return float(compute_features(rows, timeframe=timeframe.value).atr or 0.0) or None
        except InsufficientDataError:
            return None
        except Exception as exc:  # noqa: BLE001 - a cold toolkit is not an error
            logger.info("atr_unavailable", symbol=symbol, error=str(exc))
            return None


@dataclass
class ProcessingResult:
    """What one pass over the queue did."""

    processed: int = 0
    executed: int = 0
    rejected: int = 0
    ignored: int = 0
    deferred: int = 0
    reasons: list[str] = field(default_factory=list)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ProcessingResult(processed={self.processed}, executed={self.executed}, "
            f"rejected={self.rejected}, ignored={self.ignored}, deferred={self.deferred})"
        )


@dataclass
class Decision:
    """The outcome for a single signal, before anything is written."""

    status: str
    reason: str
    order_id: str | None = None


class SignalProcessor:
    """Drains the pending-signal queue through the risk-gated path."""

    def __init__(
        self,
        *,
        executor: OrderExecutor,
        risk,
        portfolio,
        signals,
        strategies,
        quotes: "QuoteProvider",
        settings,
        mode: TradingMode = TradingMode.PAPER,
        batch_size: int = 20,
        max_age: timedelta = timedelta(hours=6),
        evaluate_symbol: "Callable[[str], dict] | None" = None,
    ) -> None:
        self.executor = executor
        self.risk = risk
        self.portfolio = portfolio
        self.signals = signals
        self.strategies = strategies
        self.quotes = quotes
        self.settings = settings
        self.mode = mode
        self.batch_size = batch_size
        self.max_age = max_age
        #: Re-evaluates a symbol's strategies for a trigger. Set by the worker,
        #: which shares the paper loop. None in isolation, where a trigger from
        #: an unknown strategy is simply refused.
        self.evaluate_symbol = evaluate_symbol

    # ── public API ──────────────────────────────────────────────────────────

    def process_pending(self) -> ProcessingResult:
        """Assess and act on every pending signal, oldest first."""
        result = ProcessingResult()
        for row in self.signals.pending(limit=self.batch_size):
            result.processed += 1
            decision = self.handle(self.signals.to_schema(row))
            if decision.status == "executed":
                result.executed += 1
            elif decision.status == "rejected":
                result.rejected += 1
            elif decision.status == "ignored":
                result.ignored += 1
            else:
                result.deferred += 1
            if decision.reason:
                result.reasons.append(decision.reason)
        if result.processed:
            logger.info("signal_queue_drained", **{k: v for k, v in vars(result).items() if k != "reasons"})
        return result

    def handle(self, signal: Signal) -> Decision:
        """Decide and act on one signal.

        A decision is always recorded, including the refusals: an alert that was
        declined and left no trace is indistinguishable from an alert that was
        never delivered.
        """
        if not signal.id:
            # Nothing was recorded, so there is no row to settle the outcome on.
            # Persisting first is what makes the outcome auditable.
            raise ValueError("cannot process a signal that has not been recorded")

        if signal.action is SignalAction.HOLD:
            return self._settle(signal.id, "ignored", "hold carries no order")

        created_at = getattr(signal, "created_at", None) or utcnow()
        if self._age(created_at) > self.max_age:
            return self._settle(
                signal.id, "ignored", f"signal is older than {self.max_age}"
            )

        status = self.strategies.get(signal.strategy)
        if status is None:
            # Not one of ours. A TradingView alert normally carries only a
            # symbol and a direction, so "unknown strategy" is the common case,
            # not a mistake - and refusing it would make the integration
            # useless. An alert is a request to look, not an instruction on
            # what to buy, so the qualified strategies are asked instead. Their
            # signals carry their own entries, stops and sizes, so the resulting
            # order is traceable to reasoning rather than to the sender.
            return self._handle_as_trigger(signal)

        quote = self._quote(symbol=signal.symbol, timeframe=signal.timeframe)
        if quote is None:
            # Leave it pending: the feed may simply be behind. The age bound
            # above keeps it from lingering forever.
            logger.warning("signal_deferred_no_quote", symbol=signal.symbol)
            return Decision(status="deferred", reason=f"no quote for {signal.symbol}")

        effective, adjustment = self._effective_signal(signal, quote)
        if effective is None:
            return self._settle(signal.id, "rejected", adjustment or "no actionable request")
        if adjustment:
            # The sender's protective levels were not used as sent. That fact
            # belongs on the signal, so it is carried into the outcome reason
            # rather than living only in the log.
            logger.info("signal_levels_adjusted", signal_id=signal.id, adjustment=adjustment)

        request = self._request_from_signal(effective)
        if request is None:
            return self._settle(signal.id, "rejected", "no actionable request from these levels")

        portfolio = self.portfolio.build_snapshot(self.mode.value)
        assessment = self.risk.assess(
            request,
            portfolio,
            ticker=quote.ticker,
            signal=effective,
            strategy_status=StrategyStatus(status.status),
            atr=quote.atr or signal.atr,
        )
        if not assessment.allowed:
            return self._settle(
                signal.id,
                "rejected",
                "; ".join(filter(None, (adjustment, describe_rejection(assessment)))),
            )

        try:
            outcome = self.executor.execute(
                request, assessment, ticker=quote.ticker, portfolio=portfolio
            )
        except ExecutionRejected as exc:
            return self._settle(signal.id, "rejected", str(exc))

        return self._settle(
            signal.id,
            "executed",
            "; ".join(
                filter(
                    None,
                    (adjustment, f"{outcome.status} {assessment.approved_quantity} {effective.symbol}"),
                )
            ),
            order_id=outcome.order_id,
        )

    def _handle_as_trigger(self, signal: Signal) -> Decision:
        """Consult the strategies for this symbol instead of the sender.

        The trigger itself produces no order: any order comes from a strategy
        signal, linked to that signal rather than to this row. So the trigger is
        recorded as *ignored*, with a note saying what the strategies concluded.
        A trigger that is marked executed would imply the alert's own numbers
        were traded, which they were not.
        """
        if self.evaluate_symbol is None:
            return self._settle(
                signal.id,
                "rejected",
                f"{signal.strategy!r} is not a registered strategy and no "
                f"evaluator is available to re-check this market",
            )

        try:
            outcome = self.evaluate_symbol(signal.symbol)
        except Exception as exc:  # noqa: BLE001 - a bad symbol must not stall the queue
            logger.warning("trigger_evaluation_failed", symbol=signal.symbol, error=str(exc))
            return Decision(
                status="deferred", reason=f"evaluating {signal.symbol} failed: {exc}"
            )

        return self._settle(
            signal.id,
            "ignored",
            (
                f"trigger: qualified strategies reviewed {signal.symbol} and "
                f"produced {outcome['signals']} signal(s); "
                f"{outcome['orders_sent']} order(s) sent"
            ),
        )

    # ── internals ───────────────────────────────────────────────────────────

    def _settle(
        self,
        signal_id: str,
        status: str,
        reason: str,
        *,
        order_id: str | None = None,
    ) -> Decision:
        """Write the outcome, whichever way it went."""
        if status == "executed" and order_id:
            self.signals.mark_executed(signal_id, order_id)
        elif status == "ignored":
            self.signals.mark_ignored(signal_id, reason)
        elif status == "rejected":
            self.signals.mark_rejected(signal_id, reason)
        logger.info(
            "signal_settled",
            signal_id=signal_id,
            status=status,
            order_id=order_id,
            reason=reason,
        )
        return Decision(status=status, reason=reason, order_id=order_id)

    def _effective_signal(
        self, signal: Signal, quote: MarketQuote
    ) -> tuple[Signal | None, str | None]:
        """The signal as it will actually be traded, with a defensible stop.

        Sizing comes from stop distance, so the sender's stop is treated as a
        claim to be checked, not an instruction. When ATR is available the stop
        is placed a fixed distance below entry and the sender's value is only
        honoured if it is *wider* (less size, more caution). A tighter stop is
        replaced. This is the reason an alert cannot inflate position size.

        The result is a new Signal, and it is the one that gets assessed. If the
        engine judged the sender's original levels while the order used the
        corrected ones, the audit trail would describe a trade that never
        happened - the assessed object has to be the submitted object.
        """
        sender_entry = float(signal.entry or 0.0)
        if sender_entry <= 0:
            return None, "signal has no usable entry price"

        # A market order fills at the live price, not at whatever the alert
        # said. Anchoring the stop to the sender's entry would place it in the
        # wrong place whenever the two differ - and sizing off that wrong
        # distance compounds it. The alert's price is context, not the fill.
        entry = float(quote.price)
        if entry <= 0:
            return None, "no usable live price to anchor the stop to"

        atr = quote.atr or signal.atr
        stop = signal.stop_loss
        note: str | None = None

        drift = abs(entry - sender_entry) / entry * 100
        if drift > STALE_ENTRY_TOLERANCE_PCT:
            note = (
                f"alert priced at {sender_entry}, live is {entry} ({drift:.2f}% apart); "
                f"stop and size anchored to the live price"
            )

        if signal.action is SignalAction.BUY:
            if atr and atr > 0:
                derived = round(entry - 2.0 * atr, 8)
                if stop is None:
                    stop = derived
                    note = _join(note, f"stop absent; set {stop} from 2xATR")
                elif stop >= entry:
                    stop = derived
                    note = _join(
                        note, f"stop {signal.stop_loss} was not below entry; set {stop} from 2xATR"
                    )
                elif entry - stop < MIN_STOP_ATR_MULTIPLE * atr:
                    wider = round(entry - 2.0 * atr, 8)
                    note = _join(
                        note,
                        f"stop {signal.stop_loss} closer than {MIN_STOP_ATR_MULTIPLE}xATR; "
                        f"widened to {wider}",
                    )
                    stop = wider
            else:
                # No volatility to reason with: refuse rather than guess a stop.
                return None, "no ATR available, so the protective stop cannot be set"
        else:
            if atr and atr > 0 and (stop is None or stop <= entry):
                stop = round(entry + 2.0 * atr, 8)
                note = _join(note, f"sell stop absent or below entry; set {stop} from 2xATR")

        effective = signal.model_copy(
            update={"entry": entry, "stop_loss": stop}
        )
        if not effective.is_actionable:
            # Said plainly here, because the engine's generic "not actionable"
            # would leave whoever configured the alert guessing.
            reason = (
                "no take-profit target, so risk/reward cannot be established"
                if effective.take_profit is None
                else (
                    f"risk/reward {effective.risk_reward:.2f} is below the 1.0 minimum "
                    f"once the stop is set to {stop}"
                )
            )
            return None, _join(note, reason)

        return effective, note

    def _request_from_signal(self, signal: Signal) -> OrderRequest | None:
        """Translate an already-vetted signal into an order request."""
        quantity = self._size_for(float(signal.entry), signal.stop_loss)
        if quantity <= 0:
            return None

        return OrderRequest(
            symbol=signal.symbol,
            side=OrderSide.BUY if signal.action is SignalAction.BUY else OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=quantity,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy=signal.strategy,
            signal_id=signal.id,
            mode=self.mode,
        )

    def _size_for(self, entry: float, stop: float | None) -> float:
        """ATR-consistent sizing: risk budget divided by stop distance.

        Same arithmetic as the paper loop, so an alert and a generated signal
        of the same shape get the same size. The risk engine still caps it.
        """
        if stop is None:
            return 0.0
        distance = abs(entry - stop)
        if distance <= 0:
            return 0.0
        equity = float(self.settings.starting_equity_usd)
        pct = float(self.settings.risk_max_risk_per_trade_pct)
        return round((equity * pct / 100) / distance, 8)

    def _quote(self, *, symbol: str, timeframe: Timeframe) -> MarketQuote | None:
        """The live quote, or None if the feed cannot be reached.

        Deliberately no synthetic fallback here. The paper loop may fall back to
        synthetic prices because its output is a simulation; this processor acts
        on a third party's instruction, so a missing feed leaves the signal
        queued rather than trading a made-up price. The age bound in ``handle``
        is what stops it queuing forever.
        """
        try:
            return self.quotes.quote(symbol, timeframe)
        except Exception as exc:  # noqa: BLE001 - a bad feed must not crash the worker
            logger.warning("quote_unavailable", symbol=symbol, error=str(exc))
            return None

    @staticmethod
    def _age(created_at: datetime) -> timedelta:
        now = utcnow()
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=now.tzinfo)
        return now - created_at


class StandaloneQuoteProvider(CollectorQuoteProvider):
    """For use outside the paper loop: owns an event loop for the collector.

    A collector's HTTP client is bound to the loop that created it, so a
    provider standing alone has to bring its own and close it with the collector.
    """

    def __init__(self, collector, session, **kwargs) -> None:
        from src.database.repositories import CandleRepository

        self._collector = collector
        self._loop = asyncio.new_event_loop()
        super().__init__(
            fetch_ticker=lambda symbol: asyncio.run_coroutine_threadsafe(
                collector.fetch_ticker(symbol), self._loop
            ).result(),
            candles=CandleRepository(session),
            **kwargs,
        )

    def close(self) -> None:
        closer = getattr(self._collector, "close", None)
        if callable(closer):
            try:
                asyncio.run_coroutine_threadsafe(closer(), self._loop).result(timeout=10)
            except Exception as exc:  # noqa: BLE001 - shutdown must not raise
                logger.warning("collector_close_failed", error=str(exc))
        self._loop.close()


def signal_processor_from_loop(loop) -> SignalProcessor:
    """Build a processor that shares the paper loop's broker and collectors.

    Reuse is the point: one broker, one risk engine, one set of pooled HTTP
    clients. A second set would mean a second event loop and a second view of
    the same balances.
    """
    return SignalProcessor(
        executor=loop.executor,
        risk=loop.risk,
        portfolio=loop.portfolio,
        signals=loop.signals,
        strategies=loop.strategies,
        quotes=CollectorQuoteProvider(
            loop._fetch_ticker,  # noqa: SLF001 - one deliberate seam, see above
            loop.candles,
            timeframe=Timeframe(loop.settings.trading_timeframe),
        ),
        settings=loop.settings,
        mode=loop.mode,
        # An alert from outside names no strategy of ours, so the loop is also
        # how that market gets re-evaluated. Sharing it keeps one event loop.
        evaluate_symbol=lambda symbol: _as_outcome(loop.run_symbol(symbol)),
    )


def _as_outcome(cycle) -> dict:
    """Reduce a cycle result to what a trigger note needs."""
    return {
        "signals": cycle.signals,
        "orders_sent": cycle.orders_sent,
        "orders_rejected": cycle.orders_rejected,
        "positions_closed": cycle.positions_closed,
        "errors": cycle.errors,
    }


def build_signal_processor(
    session, settings, *, mode: TradingMode | None = None
) -> SignalProcessor:
    """Wire a processor against the session's repositories."""
    from src.database.repositories import (
        PortfolioRepository,
        SignalRepository,
        StrategyStatusRepository,
    )
    from src.market.collectors import build_collector
    from src.risk.risk_engine import RiskEngine
    from src.trading.executor import build_paper_executor

    return SignalProcessor(
        executor=build_paper_executor(session, settings),
        risk=RiskEngine(settings),
        portfolio=PortfolioRepository(session),
        signals=SignalRepository(session),
        strategies=StrategyStatusRepository(session),
        quotes=StandaloneQuoteProvider(build_collector(settings), session),
        settings=settings,
        mode=mode or TradingMode(settings.trading_mode),
    )


__all__ = [
    "CollectorQuoteProvider",
    "StandaloneQuoteProvider",
    "Decision",
    "ProcessingResult",
    "QuoteProvider",
    "SignalProcessor",
    "build_signal_processor",
    "signal_processor_from_loop",
]