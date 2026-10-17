"""Donchian-style breakout strategy.

Enters when price breaks the highest high of the prior N bars. The stop sits
below the breakout bar's low, which is the structurally invalidation level for
this setup — an arbitrary ATR stop would not correspond to anything the market
expressed.
"""

from __future__ import annotations

from src.core.enums import SignalAction, Timeframe
from src.schemas.market import Candle, IndicatorSnapshot
from src.schemas.signal import Rationale, Signal
from src.strategies.base import Strategy, StrategyContext, StrategyParams


class BreakoutStrategy(Strategy):
    name = "breakout"
    version = "1.0"
    description = "Donchian channel breakout with a volatility-squeeze precondition and volume confirmation."
    supports_short = True
    warmup_bars = 60

    def __init__(self, params: StrategyParams | None = None) -> None:
        super().__init__(params)
        self.lookback = int(params.get("lookback", 20) if params else 20)
        self.risk_reward = params.get("risk_reward", 2.5) if params else 2.5
        self.min_breakout_pct = params.get("min_breakout_pct", 0.1) if params else 0.1

    def evaluate(self, context: StrategyContext) -> Signal | None:
        self.validate_context(context)
        candles = context.candles
        indicators = context.indicators

        # Exclude the current bar: the "prior N bars" high must not include the
        # bar being tested, or every bar trivially breaks its own channel.
        window = candles[-(self.lookback + 1) : -1]
        if len(window) < self.lookback:
            self.hold_signal(context, "insufficient breakout history")
            return None

        prior_high = max(c.high for c in window)
        prior_low = min(c.low for c in window)
        current = candles[-1]
        entry = current.close

        breakout_up = current.close > prior_high * (1 + self.min_breakout_pct / 100)
        breakout_down = current.close < prior_low * (1 - self.min_breakout_pct / 100)

        if not breakout_up and not breakout_down:
            self.hold_signal(context, "no channel break")
            return None

        # A squeeze before the break distinguishes a real expansion from a
        # drift through a range that was never compressed.
        squeeze = bool(indicators.bollinger_width is not None and indicators.bollinger_width < 0.05)
        volume_confirmed = bool(indicators.volume_ratio is None or indicators.volume_ratio >= 1.3)
        trending = bool(indicators.adx is None or indicators.adx > 20)

        conditions = {
            "channel_break": True,
            "volume_confirmation": volume_confirmed,
            "volatility_expansion": squeeze or self._expanding(indicators),
            "trend_present": trending,
        }
        score = sum(conditions.values())
        if score < 3:
            self.hold_signal(context, f"breakout unconfirmed (score {score}/4)")
            return None

        if breakout_up:
            action = SignalAction.BUY
            stop_loss = self._stop_below(current, prior_low, indicators)
        else:
            if not self.supports_short:
                return None
            action = SignalAction.SELL
            stop_loss = self._stop_above(current, prior_high, indicators)

        if stop_loss <= 0 or stop_loss == entry:
            stop_loss = self.build_stop_loss(entry, action, indicators.atr)

        take_profit = self.build_take_profit(entry, stop_loss, self.risk_reward, action)

        rationale = [
            Rationale(
                claim=label.replace("_", " "),
                direction="bullish" if action is SignalAction.BUY else "bearish",
                weight=1.0 if met else 0.3,
            )
            for label, met in conditions.items()
        ]
        confidence = self.confidence(
            alignment=score / 4,
            volume_factor=indicators.volume_ratio or 1.0,
            trend_factor=min((indicators.adx or 20) / 40, 1.0),
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

    @staticmethod
    def _expanding(indicators: IndicatorSnapshot) -> bool:
        return bool(indicators.bollinger_width is not None and indicators.bollinger_width > 0.03)

    def _stop_below(self, current: Candle, prior_low: float, indicators: IndicatorSnapshot) -> float:
        """Below both the breakout bar's low and the prior channel low."""
        candidates = [current.low * 0.999, prior_low * 0.995]
        if indicators.atr:
            candidates.append(current.close - indicators.atr)
        return round(min(candidates), 8)

    def _stop_above(self, current: Candle, prior_high: float, indicators: IndicatorSnapshot) -> float:
        candidates = [current.high * 1.001, prior_high * 1.005]
        if indicators.atr:
            candidates.append(current.close + indicators.atr)
        return round(max(candidates), 8)


def build_context(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    indicators: IndicatorSnapshot,
    params: StrategyParams | None = None,
) -> StrategyContext:
    from src.strategies.base import StrategyContext

    return StrategyContext(
        symbol=symbol,
        timeframe=timeframe,
        candles=candles,
        indicators=indicators,
        params=params or StrategyParams(),
    )
