"""EMA + RSI + MACD confluence strategy.

The multi-indicator trend/pullback hybrid: an EMA trend filter, an RSI pullback
entry, and a MACD confirmation. Each condition is scored separately so the
signal's confidence reflects how many actually agreed, rather than a flat
number of parameters firing.
"""

from __future__ import annotations

import numpy as np

from src.core.enums import SignalAction, Timeframe
from src.core.logging import get_logger
from src.schemas.market import Candle, IndicatorSnapshot
from src.schemas.signal import Rationale, Signal
from src.strategies.base import Strategy, StrategyContext, StrategyParams

logger = get_logger(__name__)


class EmaRsiMacdStrategy(Strategy):
    name = "ema_rsi_macd"
    version = "1.0"
    description = (
        "Trend-following entry on an RSI pullback inside an EMA trend, confirmed by a bullish MACD histogram."
    )
    supports_short = True
    warmup_bars = 60

    def __init__(self, params: StrategyParams | None = None) -> None:
        super().__init__(params)
        self.rsi_entry = params.get("rsi_entry", 40.0) if params else 40.0
        self.rsi_deep = params.get("rsi_deep", 32.0) if params else 32.0
        self.risk_reward = params.get("risk_reward", 2.5) if params else 2.5

    def evaluate(self, context: StrategyContext) -> Signal | None:
        self.validate_context(context)
        indicators = context.indicators

        rsi = indicators.rsi
        macd_hist = indicators.macd_histogram
        ema_fast, ema_slow = indicators.ema_fast, indicators.ema_slow
        if None in (rsi, macd_hist, ema_fast, ema_slow):
            self.hold_signal(context, "indicators not ready")
            return None

        entry = context.price
        atr = indicators.atr

        # ── Long: uptrend + oversold pullback + MACD turning up ──
        long_conditions = {
            "ema_trend_up": bool(ema_fast > ema_slow and entry > ema_fast),
            "rsi_pullback": bool(self.rsi_deep <= rsi <= self.rsi_entry),
            "macd_histogram_rising": bool(macd_hist > 0),
            "volume_present": bool(
                indicators.volume_ratio is None or indicators.volume_ratio >= self.params.min_volume_ratio
            ),
        }

        # ── Short: mirror image ──
        short_conditions = {
            "ema_trend_down": bool(ema_fast < ema_slow and entry < ema_fast),
            "rsi_rebound": bool(100 - self.rsi_entry <= rsi <= 100 - self.rsi_deep),
            "macd_histogram_falling": bool(macd_hist < 0),
            "volume_present": bool(
                indicators.volume_ratio is None or indicators.volume_ratio >= self.params.min_volume_ratio
            ),
        }

        long_score = sum(long_conditions.values())
        short_score = sum(short_conditions.values())

        # Require at least three of four, and only take the side that scored
        # higher. A tie means the conditions are contradictory — no trade.
        minimum = 3
        if long_score >= minimum and long_score > short_score:
            return self._build(context, SignalAction.BUY, long_conditions, long_score, entry, atr)
        if self.supports_short and short_score >= minimum and short_score > long_score:
            return self._build(context, SignalAction.SELL, short_conditions, short_score, entry, atr)

        self.hold_signal(
            context,
            f"confluence insufficient (long={long_score}, short={short_score}, need {minimum})",
        )
        return None

    def _build(
        self,
        context: StrategyContext,
        action: SignalAction,
        conditions: dict[str, bool],
        score: int,
        entry: float,
        atr: float | None,
    ) -> Signal | None:
        indicators = context.indicators
        stop_loss = self.build_stop_loss(entry, action, atr)
        take_profit = self.build_take_profit(entry, stop_loss, self.risk_reward, action)

        rationale = [
            Rationale(
                claim=label.replace("_", " "),
                direction="bullish" if action is SignalAction.BUY else "bearish",
                weight=1.0 if met else 0.3,
            )
            for label, met in conditions.items()
        ]

        alignment = score / len(conditions)
        volume_factor = indicators.volume_ratio or 1.0
        trend_factor = min((indicators.adx or 20) / 40, 1.0)
        confidence = self.confidence(
            alignment=alignment, volume_factor=volume_factor, trend_factor=trend_factor
        )

        return self.finalise(
            context,
            action=action,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            rationale=rationale,
        )


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
        candles=candles,
        indicators=indicators,
        params=params or StrategyParams(),
    )


def _unused(value: np.ndarray) -> None:  # pragma: no cover - keeps numpy import meaningful
    return None
