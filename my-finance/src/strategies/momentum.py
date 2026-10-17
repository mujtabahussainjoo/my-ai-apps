"""Rate-of-change momentum strategy.

Buys sustained multi-bar momentum with above-average participation. Unlike the
pullback strategies it does not require a counter-trend entry: it rides an
established move, so its stop is tighter and its targets further.
"""

from __future__ import annotations

from src.core.enums import SignalAction
from src.schemas.signal import Rationale, Signal
from src.strategies.base import Strategy, StrategyContext


class MomentumStrategy(Strategy):
    name = "momentum"
    version = "1.0"
    description = "Multi-bar rate-of-change continuation with volume confirmation."
    supports_short = True
    warmup_bars = 60

    def __init__(self, params=None) -> None:
        super().__init__(params)
        self.roc_period = int(params.get("roc_period", 10) if params else 10)
        self.min_roc_pct = params.get("min_roc_pct", 2.0) if params else 2.0
        self.risk_reward = params.get("risk_reward", 3.0) if params else 3.0

    def evaluate(self, context: StrategyContext) -> Signal | None:
        self.validate_context(context)
        candles = context.candles
        indicators = context.indicators

        if len(candles) <= self.roc_period:
            self.hold_signal(context, "insufficient history for ROC")
            return None

        entry = context.price
        past = candles[-(self.roc_period + 1)].close
        if past <= 0:
            return None
        roc_pct = (entry - past) / past * 100

        rising = roc_pct >= self.min_roc_pct
        falling = roc_pct <= -self.min_roc_pct
        if not rising and not falling:
            self.hold_signal(context, f"ROC {roc_pct:+.2f}% below threshold")
            return None

        action = SignalAction.BUY if rising else SignalAction.SELL
        if action is SignalAction.SELL and not self.supports_short:
            return None

        conditions = {
            "momentum_present": True,
            "ema_aligned": indicators.ema_state == ("bullish" if rising else "bearish"),
            "macd_aligned": indicators.macd_state == ("bullish" if rising else "bearish"),
            "volume_above_average": bool(
                indicators.volume_ratio is not None and indicators.volume_ratio >= 1.2
            ),
        }
        score = sum(conditions.values())
        # Momentum trades need stronger evidence than pullback trades: they
        # enter at worse prices and pay more in slippage.
        if score < 3:
            self.hold_signal(context, f"momentum unconfirmed (score {score}/4)")
            return None

        # Tighten the stop relative to the ATR default: a momentum entry that
        # gives back 2 ATR has already invalidated the thesis.
        stop_loss = self.build_stop_loss(entry, action, indicators.atr, fallback_pct=1.2)
        take_profit = self.build_take_profit(entry, stop_loss, self.risk_reward, action)

        rationale = [
            Rationale(
                claim=label.replace("_", " "),
                direction="bullish" if rising else "bearish",
                weight=1.0 if met else 0.3,
            )
            for label, met in conditions.items()
        ]
        rationale.append(
            Rationale(
                claim=f"{self.roc_period}-bar ROC is {roc_pct:+.2f}%",
                direction="bullish" if rising else "bearish",
                weight=1.2,
            )
        )

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
