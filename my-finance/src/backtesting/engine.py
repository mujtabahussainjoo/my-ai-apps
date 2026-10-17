"""Event-driven backtest engine.

Bar-by-bar, in strict chronological order, with no lookahead. The invariant
that makes results trustworthy:

    At bar *i* the engine may only use candles[0..i] and trades opened at or
    before bar *i*. Signals are computed on the bar that closes, and fills
    happen at the *next* bar's open.

That last part matters. Filling at the close of the bar that produced the
signal assumes you knew the close before it printed, which quietly inflates
every result.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256
from itertools import count
from uuid import uuid4

from src.backtesting.simulator import FillSimulator, round_down
from src.core.config import Settings, get_settings
from src.core.constants import PIVOT_RIGHT
from src.core.enums import OrderSide, SignalAction, Timeframe, TradingMode
from src.core.exceptions import BacktestError, InsufficientDataError
from src.core.logging import get_logger
from src.core.security import idempotency_key
from src.evaluation.metrics import compute_metrics
from src.schemas.market import Candle, IndicatorSnapshot
from src.schemas.portfolio import PerformanceMetrics
from src.schemas.signal import Signal
from src.schemas.trade import Trade
from src.strategies import registry as strategy_registry
from src.strategies.base import StrategyParams

logger = get_logger(__name__)

#: Indicator warm-up. No signal can be generated before this bar.
WARMUP_BARS = 60


@dataclass(slots=True)
class OpenPosition:
    """An in-flight position inside the backtest."""

    signal: Signal
    quantity: float
    entry_price: float
    entry_index: int
    entry_time: datetime
    stop_loss: float
    take_profit: float
    initial_risk_per_unit: float
    fees_paid: float = 0.0


@dataclass(slots=True)
class BacktestConfig:
    """Everything that defines a run, recorded so it can be reproduced."""

    strategy: str
    symbol: str
    timeframe: Timeframe = Timeframe.H1
    starting_equity: float = 10_000.0
    risk_pct_per_trade: float = 1.0
    max_position_pct: float = 95.0
    max_open_positions: int = 3
    params: StrategyParams = field(default_factory=StrategyParams)
    start: datetime | None = None
    end: datetime | None = None
    #: Bars to skip at the start to exclude from the equity curve.
    label: str | None = None
    input_hash: str | None = None

    @property
    def run_id(self) -> str:
        return idempotency_key("backtest", json.dumps(asdict(self), default=str, sort_keys=True))[:16]


@dataclass(slots=True)
class BacktestResult:
    config: BacktestConfig
    trades: list[Trade]
    metrics: PerformanceMetrics
    equity_curve: list[float]
    signals_generated: int = 0
    signals_rejected_by_risk: int = 0
    bars_processed: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    out_of_sample: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def run_id(self) -> str:
        return self.config.run_id

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "strategy": self.config.strategy,
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe.value,
            "out_of_sample": self.out_of_sample,
            "signals_generated": self.signals_generated,
            "signals_rejected_by_risk": self.signals_rejected_by_risk,
            "bars_processed": self.bars_processed,
            "trades": len(self.trades),
            "metrics": self.metrics.model_dump(mode="json"),
            "equity_curve": [round(v, 2) for v in self.equity_curve],
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "notes": self.notes,
        }


class BacktestEngine:
    """Runs one strategy over one symbol's history."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.simulator = FillSimulator(self.settings)
        self._order_ids = count(1)

    def run(
        self,
        candles: list[Candle],
        config: BacktestConfig,
        *,
        out_of_sample: bool = False,
    ) -> BacktestResult:
        series = self._prepare(candles, config)
        identity = json.dumps(
            [self.settings.fee_bps, self.settings.slippage_bps, [c.model_dump(mode="json") for c in series]],
            sort_keys=True,
        )
        config = replace(config, input_hash=sha256(identity.encode()).hexdigest())
        notes: list[str] = []
        started = datetime.now(UTC)

        equity = config.starting_equity
        peak_equity = equity
        curve: list[float] = []
        trades: list[Trade] = []
        open_positions: list[OpenPosition] = []
        signals_generated = 0
        signals_rejected = 0
        bars_processed = 0

        # Indicators are computed once over the full series, then read at bar
        # i. This is equivalent to recomputing causally per bar and is ~100x
        # faster; correctness is preserved because every value at index i uses
        # only inputs up to index i.
        features = compute_series_for(series)

        for index in range(WARMUP_BARS, len(series)):
            bars_processed += 1
            candle = series[index]

            # ── 1. Manage exits first: capital must free up before entries ──
            for position in list(open_positions):
                decision = self.simulator.check_exit(
                    candle,
                    side="buy" if position.signal.action is SignalAction.BUY else "sell",
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                )
                if decision.should_exit and decision.price is not None:
                    trade = self._close(position, decision.price, candle, decision.reason)
                    trades.append(trade)
                    equity += self._close_cash_delta(trade, position)
                    open_positions.remove(position)
                    peak_equity = max(peak_equity, self._total_equity(equity, open_positions, candle))

            curve.append(self._total_equity(equity, open_positions, candle))
            peak_equity = max(peak_equity, curve[-1])

            # ── 2. Look for a new entry ──
            if len(open_positions) >= config.max_open_positions:
                continue

            snapshot = self._snapshot_at(features, index, series[index], config)
            if snapshot is None:
                continue

            signal = strategy_registry.evaluate(
                config.strategy,
                config.symbol,
                config.timeframe,
                series[: index + 1],
                snapshot,
                config.params,
            )
            if signal is None:
                continue
            signals_generated += 1

            # Only the most recent bar may open a position, and fills happen at
            # the next bar's open — see the module docstring.
            if index + 1 >= len(series):
                continue
            next_open = series[index + 1].open

            sizing = self._size_position(
                equity=equity,
                entry=next_open,
                stop_loss=signal.stop_loss or next_open * 0.99,
                risk_pct=config.risk_pct_per_trade,
                max_position_pct=config.max_position_pct,
            )
            if sizing is None:
                signals_rejected += 1
                notes.append(f"bar {index}: position sizing rejected the signal")
                continue

            quantity, notional = sizing
            if notional < 10.0:
                signals_rejected += 1
                continue
            if notional > equity:
                signals_rejected += 1
                continue

            fill = self.simulator.simulate_market_fill(
                "buy" if signal.action is SignalAction.BUY else "sell", next_open, quantity
            )
            initial_risk = abs(fill.price - (signal.stop_loss or fill.price))

            open_positions.append(
                OpenPosition(
                    signal=signal,
                    quantity=quantity,
                    entry_price=fill.price,
                    entry_index=index + 1,
                    entry_time=series[index + 1].timestamp,
                    stop_loss=signal.stop_loss or fill.price,
                    take_profit=signal.take_profit or fill.price,
                    initial_risk_per_unit=initial_risk,
                    fees_paid=fill.fee_usd,
                )
            )
            equity -= fill.fee_usd

        # Close anything still open at the last price so the metrics reflect
        # realised, not floating, results.
        if open_positions:
            last = series[-1]
            for position in open_positions:
                trade = self._close(position, last.close, last, "end_of_data")
                trades.append(trade)
                equity += self._close_cash_delta(trade, position)
                curve.append(equity)  # positions fully closed; cash == equity
            notes.append(
                f"{len(open_positions)} position(s) still open at the end of the "
                f"window were closed at the final close for metric purposes"
            )

        metrics = compute_metrics(trades, starting_equity=config.starting_equity)
        result = BacktestResult(
            config=config,
            trades=trades,
            metrics=metrics,
            equity_curve=curve,
            signals_generated=signals_generated,
            signals_rejected_by_risk=signals_rejected,
            bars_processed=bars_processed,
            started_at=started,
            finished_at=datetime.now(UTC),
            out_of_sample=out_of_sample,
            notes=notes,
        )
        logger.info(
            "backtest_complete",
            strategy=config.strategy,
            symbol=config.symbol,
            trades=len(trades),
            win_rate=round(metrics.win_rate, 4),
            profit_factor=round(metrics.profit_factor, 3) if metrics.profit_factor != float("inf") else "inf",
            max_dd=round(metrics.max_drawdown_pct, 2),
            net_profit=round(metrics.net_profit_usd, 2),
            oos=out_of_sample,
        )
        return result

    # ── helpers ──
    def _prepare(self, candles: list[Candle], config: BacktestConfig) -> list[Candle]:
        series = sorted(candles, key=lambda c: c.timestamp)
        if config.start:
            series = [c for c in series if c.timestamp >= config.start]
        if config.end:
            series = [c for c in series if c.timestamp <= config.end]
        if len(series) < WARMUP_BARS + 60:
            raise InsufficientDataError(
                f"backtest needs at least {WARMUP_BARS + 60} candles, got {len(series)}"
            )
        return series

    def _size_position(
        self,
        *,
        equity: float,
        entry: float,
        stop_loss: float,
        risk_pct: float,
        max_position_pct: float,
    ) -> tuple[float, float] | None:
        """Fixed-fractional sizing, capped by position value."""
        stop_distance = abs(entry - stop_loss)
        if stop_distance <= 0 or entry <= 0 or equity <= 0:
            return None

        risk_budget = equity * risk_pct / 100
        by_risk = risk_budget / stop_distance
        by_value = (equity * max_position_pct / 100) / entry
        quantity = round_down(min(by_risk, by_value))
        if quantity <= 0:
            return None
        return quantity, quantity * entry

    @staticmethod
    def _total_equity(cash: float, positions: list[OpenPosition], candle: Candle) -> float:
        """Cash plus mark-to-market value of open positions.

        The equity curve must include unrealised P&L, otherwise drawdown is
        measured only on closed trades and a strategy that drifts slowly
        underwater shows no drawdown at all.
        """
        unrealised = 0.0
        for position in positions:
            direction = 1 if position.signal.action is SignalAction.BUY else -1
            unrealised += (candle.close - position.entry_price) * position.quantity * direction
        return cash + unrealised

    def _close(
        self,
        position: OpenPosition,
        exit_price: float,
        candle: Candle,
        reason: str | None,
    ) -> Trade:
        side = "buy" if position.signal.action is SignalAction.BUY else "sell"
        fill = self.simulator.simulate_market_fill(
            "sell" if side == "buy" else "buy", exit_price, position.quantity
        )
        direction = 1 if side == "buy" else -1
        gross = (fill.price - position.entry_price) * position.quantity * direction
        # Net of *both* fees. The entry fee was already deducted from cash when
        # the position opened, so the caller adds it back when applying this
        # number to equity (see ``_close_cash_delta``).
        pnl = gross - position.fees_paid - fill.fee_usd
        cost = (position.entry_price + fill.price) * position.quantity
        risk_multiple = (
            pnl / (position.initial_risk_per_unit * position.quantity)
            if position.initial_risk_per_unit > 0
            else None
        )
        return Trade(
            id=f"bt-{uuid4().hex[:12]}",
            order_id=f"bt-o{next(self._order_ids)}",
            symbol=position.signal.symbol,
            side=OrderSide.BUY if position.signal.action is SignalAction.BUY else OrderSide.SELL,
            strategy=position.signal.strategy,
            quantity=position.quantity,
            entry_price=position.entry_price,
            exit_price=fill.price,
            entry_time=position.entry_time,
            exit_time=candle.timestamp,
            gross_pnl_usd=gross,
            fees_usd=position.fees_paid + fill.fee_usd,
            pnl_usd=pnl,
            pnl_pct=(pnl / cost * 100) if cost > 0 else 0.0,
            initial_risk_per_unit=position.initial_risk_per_unit,
            risk_multiple=risk_multiple,
            planned_risk_reward=position.signal.risk_reward,
            exit_reason=reason,  # type: ignore[arg-type]
            mode=TradingMode.BACKTEST,
        )

    @staticmethod
    def _close_cash_delta(trade: Trade, position: OpenPosition) -> float:
        """Cash actually received on close.

        ``trade.pnl_usd`` is net of the entry fee, but that fee left the account
        when the position opened, so it must be credited back here or it would
        be charged twice.
        """
        return trade.pnl_usd + position.fees_paid

    @staticmethod
    def _snapshot_at(
        features: dict[str, object],
        index: int,
        candle: Candle,
        config: BacktestConfig,
    ) -> IndicatorSnapshot | None:
        """Build an indicator snapshot using only bars up to ``index``."""
        try:
            return IndicatorSnapshot(
                symbol=candle.symbol,
                timeframe=config.timeframe,
                timestamp=candle.timestamp,
                close=float(candle.close),  # type: ignore[arg-type]
                rsi=_at(features.get("rsi"), index),
                macd=_at(features.get("macd"), index),
                macd_signal=_at(features.get("macd_signal"), index),
                macd_histogram=_at(features.get("macd_hist"), index),
                ema_fast=_at(features.get("ema_fast"), index),
                ema_slow=_at(features.get("ema_slow"), index),
                sma_20=_at(features.get("sma_20"), index),
                sma_50=_at(features.get("sma_50"), index),
                bollinger_upper=_at(features.get("bollinger_upper"), index),
                bollinger_middle=_at(features.get("bollinger_middle"), index),
                bollinger_lower=_at(features.get("bollinger_lower"), index),
                bollinger_width=_at(features.get("bollinger_width"), index),
                atr=_at(features.get("atr"), index),
                atr_pct=_at(features.get("atr_pct"), index),
                adx=_at(features.get("adx"), index),
                volume_ratio=_at(features.get("volume_ratio"), index),
                # A pivot is only knowable ``PIVOT_RIGHT`` bars after it forms,
                # so the newest *confirmed* pivot as of this bar is that many
                # bars back. Reading it at ``index`` would leak future bars.
                support=_pivot_at(features.get("swing_lows"), index, PIVOT_RIGHT),
                resistance=_pivot_at(features.get("swing_highs"), index, PIVOT_RIGHT),
            )
        except (TypeError, ValueError):
            return None


def _pivot_at(series: object, index: int, right: int) -> float | None:
    """Most recent pivot level confirmed as of bar ``index``.

    ``find_pivots`` needs ``right`` subsequent bars to confirm a swing, so a
    value stored at position ``j`` is only information a trader has at
    ``j + right``.
    """
    confirmed_index = index - right
    if confirmed_index < 0:
        return None
    return _at(series, confirmed_index, allow_zero=False)


def _at(series: object, index: int, *, allow_zero: bool = True) -> float | None:
    if series is None:
        return None
    try:
        value = float(series[index])  # type: ignore[index]
    except (TypeError, IndexError, ValueError):
        return None
    import math

    if math.isnan(value):
        return None
    if not allow_zero and value <= 0:
        return None
    return value


def compute_series_for(candles: list[Candle]) -> dict[str, object]:
    """Indicator series for the backtest loop (cached per call site)."""
    from src.technical_analysis.feature_engine import compute_series_features

    return dict(compute_series_features(candles))


class MultiStrategyRunner:
    """Runs several strategies over the same data for comparison."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def run(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: Timeframe = Timeframe.H1,
        *,
        strategies: list[str] | None = None,
        starting_equity: float = 10_000.0,
        risk_pct: float = 1.0,
    ) -> list[BacktestResult]:
        names = strategies or strategy_registry.all_names()
        engine = BacktestEngine(self.settings)
        results: list[BacktestResult] = []
        for name in names:
            config = BacktestConfig(
                strategy=name,
                symbol=symbol,
                timeframe=timeframe,
                starting_equity=starting_equity,
                risk_pct_per_trade=risk_pct,
            )
            try:
                results.append(engine.run(candles, config))
            except BacktestError as exc:
                logger.warning("backtest_failed", strategy=name, symbol=symbol, error=str(exc))
        return results


async def run_backtest_async(
    symbol: str,
    timeframe: Timeframe = Timeframe.H1,
    strategies: list[str] | None = None,
    limit: int = 3000,
) -> list[BacktestResult]:
    """Convenience entry point used by the API and CLI."""
    from src.backtesting.data_loader import HistoricalDataLoader

    candles = await HistoricalDataLoader().load(symbol, timeframe, limit)
    return MultiStrategyRunner().run(candles, symbol, timeframe, strategies=strategies)
