"""Strategy base classes.

Design constraints that come from Workflow.md:

- Strategies are **deterministic Python**. No LLM calls, no network, no I/O.
  A strategy must be reproducible from the same candles, or its backtest is
  meaningless.
- A strategy emits a *candidate*, never an order. It cannot size a position,
  cannot see the portfolio, and cannot reach an exchange.
- Every signal carries its own evidence (rationale) and a stop, because the
  risk engine rejects any trade without a stop regardless of what the strategy
  thinks.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from src.core.enums import SignalAction, Timeframe
from src.core.exceptions import StrategyError
from src.core.logging import get_logger
from src.schemas.market import Candle, IndicatorSnapshot
from src.schemas.signal import Rationale, Signal, SignalScore
from src.technical_analysis.indicators.atr import volatility_stop_distance

logger = get_logger(__name__)


@dataclass(slots=True)
class StrategyParams:
    """Tunable parameters. Frozen per run so a backtest cannot mutate them."""

    atr_stop_multiplier: float = 2.0
    min_risk_reward: float = 2.0
    min_volume_ratio: float = 1.0
    min_atr_pct: float = 0.1
    max_atr_pct: float = 6.0
    max_confidence: float = 0.85
    extra: dict[str, float] = field(default_factory=dict)

    def get(self, key: str, default: float) -> float:
        return self.extra.get(key, default)


@dataclass(slots=True)
class StrategyContext:
    """Everything a strategy is allowed to see.

    Deliberately narrow: no balance, no open positions, no exchange. Keeping
    the strategy blind to portfolio state means the same signal logic produces
    the same signal in backtest and live, and prevents a strategy from
    implicitly depending on portfolio size.
    """

    symbol: str
    timeframe: Timeframe
    candles: list[Candle]
    indicators: IndicatorSnapshot
    params: StrategyParams = field(default_factory=StrategyParams)

    @property
    def last_close(self) -> float:
        return self.candles[-1].close

    @property
    def previous_close(self) -> float:
        return self.candles[-2].close if len(self.candles) > 1 else self.last_close

    @property
    def price(self) -> float:
        return self.last_close


class Strategy(abc.ABC):
    """Abstract strategy."""

    name: str = "base"
    version: str = "1.0"
    description: str = ""
    #: Whether the strategy can profit from a downtrend (short side).
    supports_short: bool = True
    #: Minimum candles required before this strategy will emit anything.
    warmup_bars: int = 60

    def __init__(self, params: StrategyParams | None = None) -> None:
        self.params = params or StrategyParams()

    @abc.abstractmethod
    def evaluate(self, context: StrategyContext) -> Signal | None:
        """Return a signal, or ``None`` to express 'no setup'.

        Returning ``None`` for 'no trade' keeps HOLD signals out of the
        pipeline entirely — a HOLD is not a decision, it is the absence of one.
        """

    def validate_context(self, context: StrategyContext) -> None:
        """Structural preconditions. Subclasses may add stricter checks."""
        if len(context.candles) < self.warmup_bars:
            raise StrategyError(f"{self.name} needs {self.warmup_bars} candles, got {len(context.candles)}")
        indicators = context.indicators
        if indicators.atr_pct is not None:
            if indicators.atr_pct < self.params.min_atr_pct:
                raise StrategyError(
                    f"{self.name} skipped: ATR {indicators.atr_pct:.3f}% below "
                    f"minimum {self.params.min_atr_pct}% (market too quiet to pay for spreads)"
                )
            if indicators.atr_pct > self.params.max_atr_pct:
                raise StrategyError(
                    f"{self.name} skipped: ATR {indicators.atr_pct:.2f}% above "
                    f"maximum {self.params.max_atr_pct}% (volatility too extreme)"
                )

    def confidence(
        self,
        *,
        alignment: float,
        volume_factor: float = 1.0,
        trend_factor: float = 0.5,
    ) -> float:
        """Blend confluence factors into a bounded 0-1 score.

        ``alignment`` is the fraction of the strategy's conditions that agree
        with the direction, so a strategy with four conditions needing three to
        fire scores lower than one needing only one.
        """
        score = 0.5 * alignment + 0.25 * min(volume_factor, 2.0) / 2 + 0.25 * trend_factor
        return round(min(max(score, 0.0), self.params.max_confidence), 4)

    def build_stop_loss(
        self,
        entry: float,
        side: SignalAction,
        atr: float | None,
        fallback_pct: float = 1.5,
    ) -> float:
        """ATR-based stop, clamped into a sane band.

        Falls back to a percentage stop when ATR is unavailable so a signal is
        never emitted without protection.
        """
        distance_pct = (
            volatility_stop_distance(atr, entry, self.params.atr_stop_multiplier)
            if atr is not None and atr > 0
            else fallback_pct
        )
        distance = entry * distance_pct / 100
        return round(entry - distance if side is SignalAction.BUY else entry + distance, 8)

    def build_take_profit(
        self,
        entry: float,
        stop_loss: float,
        reward_multiple: float,
        side: SignalAction = SignalAction.BUY,
    ) -> float:
        """Place the target on the *profitable* side of entry.

        Direction is not cosmetic here. A short's target must sit below entry,
        and putting it above turns every short into a guaranteed loss that the
        exit logic then dutifully fills as a "take profit".
        """
        risk = abs(entry - stop_loss)
        target = risk * reward_multiple
        return round(entry - target if side is SignalAction.SELL else entry + target, 8)

    @staticmethod
    def levels_are_ordered(action: SignalAction, entry: float, stop_loss: float, take_profit: float) -> bool:
        """True when stop and target sit on the sides the trade requires.

        BUY:  stop < entry < target
        SELL: target < entry < stop
        """
        if action is SignalAction.BUY:
            return stop_loss < entry < take_profit
        if action is SignalAction.SELL:
            return take_profit < entry < stop_loss
        return False

    def finalise(
        self,
        context: StrategyContext,
        *,
        action: SignalAction,
        entry: float,
        stop_loss: float,
        take_profit: float,
        confidence: float,
        rationale: list[Rationale],
    ) -> Signal | None:
        """Apply the shared quality gates, then emit the signal or nothing.

        The R:R gate lives here rather than in each strategy so every strategy
        is held to the same standard — a strategy cannot opt out of it.
        """
        if not self.levels_are_ordered(action, entry, stop_loss, take_profit):
            logger.error(
                "strategy_levels_misordered",
                strategy=self.name,
                symbol=context.symbol,
                action=action.value,
                entry=entry,
                stop_loss=stop_loss,
                take_profit=take_profit,
                note="stop and target must bracket entry on their correct sides",
            )
            return None

        risk_reward = abs(take_profit - entry) / abs(entry - stop_loss) if entry != stop_loss else 0.0
        if risk_reward < self.params.min_risk_reward:
            logger.debug(
                "strategy_signal_rejected",
                strategy=self.name,
                symbol=context.symbol,
                reason="insufficient_risk_reward",
                risk_reward=round(risk_reward, 3),
                required=self.params.min_risk_reward,
            )
            return None

        return Signal(
            symbol=context.symbol,
            timeframe=context.timeframe,
            strategy=self.name,
            strategy_version=self.version,
            action=action,
            confidence=min(confidence, self.params.max_confidence),
            entry=entry,
            entry_low=round(entry * 0.999, 8),
            entry_high=round(entry * 1.001, 8),
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr=context.indicators.atr,
            rationale=rationale,
            score=score_indicators(context.indicators, action),
        )

    def hold_signal(self, context: StrategyContext, reason: str) -> None:
        logger.debug(
            "strategy_no_setup",
            strategy=self.name,
            symbol=context.symbol,
            reason=reason,
        )


def score_indicators(indicators: IndicatorSnapshot, action: SignalAction) -> SignalScore:
    """Weighted technical confluence score in the spirit of Workflow.md §21.

    Scores each component 0-100 from agreement with the proposed direction, then
    applies the configured weights. The result is labelled a *signal score* and
    explicitly not a probability of profit.
    """
    from src.core.constants import SIGNAL_SCORE_WEIGHTS

    bullish = action is SignalAction.BUY
    components: dict[str, float] = {}

    # Technical: RSI positioning and MACD alignment.
    technical = 50.0
    if indicators.rsi is not None:
        if bullish and indicators.rsi < 45:
            technical += min((45 - indicators.rsi) * 1.5, 30)
        elif not bullish and indicators.rsi > 55:
            technical += min((indicators.rsi - 55) * 1.5, 30)
        else:
            technical -= 15
    if indicators.macd_state != "unknown":
        technical += 20 if ((indicators.macd_state == "bullish") == bullish) else -20
    components["technical"] = max(0.0, min(100.0, technical))

    # Trend: EMA structure plus ADX-confirmed strength.
    trend = 50.0
    if indicators.ema_state != "unknown":
        trend += 25 if ((indicators.ema_state == "bullish") == bullish) else -25
    if indicators.adx is not None:
        trend += 15 if indicators.adx > 25 else -10
    components["trend"] = max(0.0, min(100.0, trend))

    # Volume: participation above average supports the move.
    ratio = indicators.volume_ratio
    components["volume"] = 50.0 if ratio is None else min(100.0, 30 + ratio * 35)

    # Regime: penalise trading against a strong opposing regime.
    regime_scores = {
        "bullish": {"BUY": 90.0, "SELL": 25.0},
        "bearish": {"SELL": 90.0, "BUY": 25.0},
        "range": {"BUY": 55.0, "SELL": 55.0},
        "high_volatility": {"BUY": 45.0, "SELL": 45.0},
    }
    components["market_regime"] = regime_scores.get(indicators.regime.value, {"BUY": 50.0, "SELL": 50.0})[
        action.value
    ]

    # Risk: volatility is a drag on expectancy regardless of direction.
    risk = 70.0
    if indicators.atr_pct is not None:
        risk = max(10.0, 100.0 - indicators.atr_pct * 12)
    components["risk"] = risk

    # Sentiment is intentionally absent: it is the LLM's input, not the
    # strategy's, and the strategy must stay independent of it.

    total = sum(
        SIGNAL_SCORE_WEIGHTS[key] * value for key, value in components.items() if key in SIGNAL_SCORE_WEIGHTS
    )
    return SignalScore(
        total=round(total, 2),
        components={key: round(value, 2) for key, value in components.items()},
    )
