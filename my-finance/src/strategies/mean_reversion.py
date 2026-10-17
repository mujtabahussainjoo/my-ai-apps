"""Bollinger mean-reversion strategy.

Fades a band touch when price has not previously closed outside it, and only
when the market is not trending. The ADX gate is what makes this strategy
survivable: mean reversion against a strong trend is how it loses money, so it
refuses to trade unless ADX confirms a range.
"""

from __future__ import annotations

from src.core.enums import MarketRegime, SignalAction
from src.schemas.signal import Rationale, Signal
from src.strategies.base import Strategy, StrategyContext


class MeanReversionStrategy(Strategy):
    name = "mean_reversion"
    version = "1.0"
    description = "Bollinger band fade, gated to non-trending regimes by ADX."
    supports_short = True
    warmup_bars = 60

    def __init__(self, params=None) -> None:
        super().__init__(params)
        self.percent_b_entry = params.get("percent_b_entry", 0.05) if params else 0.05
        self.max_adx = params.get("max_adx", 22.0) if params else 22.0
        self.risk_reward = params.get("risk_reward", 2.0) if params else 2.0

    def evaluate(self, context: StrategyContext) -> Signal | None:
        self.validate_context(context)
        indicators = context.indicators

        upper, lower, middle = (
            indicators.bollinger_upper,
            indicators.bollinger_lower,
            indicators.bollinger_middle,
        )
        entry = context.price
        if upper is None or lower is None or middle is None or upper <= lower:
            self.hold_signal(context, "bollinger bands unavailable")
            return None

        # Trend gate — the whole thesis depends on this.
        if indicators.adx is not None and indicators.adx > self.max_adx:
            self.hold_signal(
                context, f"ADX {indicators.adx:.1f} above {self.max_adx} (trending, do not fade)"
            )
            return None

        position = (entry - lower) / (upper - lower)  # 0 = lower band, 1 = upper
        recent = context.candles[-3:]

        conditions: dict[str, bool] = {}
        if position <= self.percent_b_entry:
            # Only fade if the band touch is new, not a continuation below it.
            closed_below_before = any(c.close < lower for c in recent[:-1])
            conditions = {
                "band_touch": True,
                "not_breaking_down": not closed_below_before,
                "not_trending": True,
                "volume_exhausted": bool(indicators.volume_ratio is None or indicators.volume_ratio < 1.5),
            }
            action = SignalAction.BUY
        elif position >= 1 - self.percent_b_entry:
            closed_above_before = any(c.close > upper for c in recent[:-1])
            conditions = {
                "band_touch": True,
                "not_breaking_up": not closed_above_before,
                "not_trending": True,
                "volume_exhausted": bool(indicators.volume_ratio is None or indicators.volume_ratio < 1.5),
            }
            action = SignalAction.SELL
        else:
            self.hold_signal(context, f"price at {position:.0%} of band, inside range")
            return None

        if action is SignalAction.SELL and not self.supports_short:
            return None

        score = sum(conditions.values())
        if score < 3:
            self.hold_signal(context, f"reversion unconfirmed (score {score}/4)")
            return None

        # Target the band mean; stop beyond the extreme.
        stop_loss = self.build_stop_loss(entry, action, indicators.atr, fallback_pct=1.0)
        band_target = middle
        take_profit = round(band_target, 8)
        # If the mean is closer than the required reward, fall back to an
        # R-multiple target rather than emitting an unacceptable setup.
        if abs(take_profit - entry) / max(abs(entry - stop_loss), 1e-9) < self.params.min_risk_reward:
            take_profit = self.build_take_profit(entry, stop_loss, self.risk_reward, action)

        direction = "bullish" if action is SignalAction.BUY else "bearish"
        rationale = [
            Rationale(claim=label.replace("_", " "), direction=direction, weight=1.0 if met else 0.3)
            for label, met in conditions.items()
        ]
        rationale.append(
            Rationale(
                claim=f"price at {position:.0%} of the Bollinger channel (mean {middle:.0f})",
                direction=direction,
                weight=1.1,
            )
        )
        if indicators.regime is MarketRegime.HIGH_VOLATILITY:
            rationale.append(Rationale(claim="regime is high volatility", direction="risk", weight=0.8))

        confidence = self.confidence(
            alignment=score / 4,
            volume_factor=indicators.volume_ratio or 1.0,
            trend_factor=1.0 - min((indicators.adx or 0) / 40, 1.0),
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
