"""Strategy registry.

A single lookup point for strategy discovery, so the API, the backtester and
the agent layer all enumerate the same set and cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterator

from src.core.enums import Timeframe
from src.core.exceptions import StrategyNotFoundError
from src.core.logging import get_logger
from src.schemas.market import Candle, IndicatorSnapshot
from src.schemas.signal import Signal
from src.strategies.base import Strategy, StrategyContext, StrategyParams
from src.strategies.breakout import BreakoutStrategy
from src.strategies.ema_rsi_macd import EmaRsiMacdStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy

logger = get_logger(__name__)

_STRATEGY_CLASSES: dict[str, type[Strategy]] = {
    EmaRsiMacdStrategy.name: EmaRsiMacdStrategy,
    BreakoutStrategy.name: BreakoutStrategy,
    MomentumStrategy.name: MomentumStrategy,
    MeanReversionStrategy.name: MeanReversionStrategy,
}


def build_context(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    indicators: IndicatorSnapshot,
    params: StrategyParams | None = None,
) -> StrategyContext:
    return StrategyContext(
        symbol=symbol,
        timeframe=timeframe,
        candles=sorted(candles, key=lambda c: c.timestamp),
        indicators=indicators,
        params=params or StrategyParams(),
    )


def create(name: str, params: StrategyParams | None = None) -> Strategy:
    """Instantiate a strategy by name."""
    try:
        return _STRATEGY_CLASSES[name](params)
    except KeyError as exc:
        raise StrategyNotFoundError(
            f"unknown strategy '{name}'. Available: {sorted(_STRATEGY_CLASSES)}"
        ) from exc


def get(name: str) -> Strategy:
    return create(name)


def all_names() -> list[str]:
    return sorted(_STRATEGY_CLASSES)


def describe() -> list[dict[str, object]]:
    """Metadata for the dashboard's strategy table."""
    return [
        {
            "name": cls.name,
            "version": cls.version,
            "description": cls.description,
            "supports_short": cls.supports_short,
            "warmup_bars": cls.warmup_bars,
        }
        for cls in sorted(_STRATEGY_CLASSES.values(), key=lambda c: c.name)
    ]


def evaluate(
    name: str,
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    indicators: IndicatorSnapshot,
    params: StrategyParams | None = None,
) -> Signal | None:
    """Build the context and run one strategy.

    Strategy errors are swallowed into a ``None`` signal: a strategy that
    cannot form a view is 'no signal', never an exception that halts the
    pipeline for every other strategy.
    """
    strategy = create(name, params)
    context = build_context(symbol, timeframe, candles, indicators, params)
    try:
        return strategy.evaluate(context)
    except Exception as exc:  # noqa: BLE001 - one strategy must not break the rest
        logger.warning(
            "strategy_evaluation_failed",
            strategy=name,
            symbol=symbol,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


def evaluate_all(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    indicators: IndicatorSnapshot,
    strategies: list[str] | None = None,
    params: StrategyParams | None = None,
) -> list[Signal]:
    """Run every strategy (or a subset) and return all actionable signals."""
    names = strategies or all_names()
    signals: list[Signal] = []
    for name in names:
        signal = evaluate(name, symbol, timeframe, candles, indicators, params)
        if signal is not None:
            signals.append(signal)
    return signals


def __iter__() -> Iterator[Strategy]:
    for name in all_names():
        yield create(name)


__all__ = [
    "Strategy",
    "StrategyContext",
    "StrategyParams",
    "all_names",
    "build_context",
    "create",
    "describe",
    "evaluate",
    "evaluate_all",
    "get",
]
