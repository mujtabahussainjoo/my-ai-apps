"""Signal and agent-decision schemas.

``AgentOutput`` schemas are the hard boundary around the LLM: the model must
produce output that validates against one of these, and any parse or
validation failure is treated as a rejection (``fail closed``).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from src.core.constants import MAX_AGENT_CONFIDENCE
from src.core.enums import AgentRole, AgentVerdict, RiskLevel, SignalAction, Timeframe
from src.schemas.base import Base, Price, Probability, utcnow


class Rationale(Base):
    """One evidence item with a direction. Keeps reasoning auditable."""

    claim: str = Field(min_length=3, max_length=300)
    direction: str = Field(default="neutral", pattern="^(bullish|bearish|neutral|risk)$")
    weight: float = Field(default=1.0, ge=0, le=5)


class SignalScore(Base):
    """Weighted confluence score (Workflow.md §21).

    Explicitly *not* a win probability: it measures how many independent
    conditions agree, which is why the disclaimer is part of the model.
    """

    total: float = Field(ge=0, le=100)
    components: dict[str, float] = Field(default_factory=dict)
    computed_at: datetime = Field(default_factory=utcnow)
    disclaimer: str = "Signal score measures technical confluence, not probability of profit."


class Signal(Base):
    """Deterministic strategy output. Contains no LLM opinion by construction."""

    #: Set when the signal was read back from storage. Absent on a signal that
    #: has not been recorded yet, which is why it is optional.
    id: str | None = None
    symbol: str
    timeframe: Timeframe = Timeframe.H1
    strategy: str
    action: SignalAction
    confidence: Probability
    entry: Price
    stop_loss: Price | None = None
    take_profit: Price | None = None
    entry_low: Price | None = None
    entry_high: Price | None = None
    atr: float | None = None
    rationale: list[Rationale] = Field(default_factory=list)
    score: SignalScore | None = None
    created_at: datetime = Field(default_factory=utcnow)
    strategy_version: str = "1.0"

    @field_validator("rationale")
    @classmethod
    def _bound_rationale(cls, value: list[Rationale]) -> list[Rationale]:
        if len(value) > 20:
            raise ValueError("rationale must contain at most 20 items")
        return value

    @property
    def risk_per_unit(self) -> float | None:
        if self.stop_loss is None:
            return None
        return abs(self.entry - self.stop_loss)

    @property
    def reward_per_unit(self) -> float | None:
        if self.take_profit is None:
            return None
        return abs(self.take_profit - self.entry)

    @property
    def risk_reward(self) -> float | None:
        risk, reward = self.risk_per_unit, self.reward_per_unit
        if risk is None or reward is None or risk <= 0:
            return None
        return reward / risk

    @property
    def stop_distance_pct(self) -> float | None:
        if self.stop_loss is None or self.entry <= 0:
            return None
        return abs(self.entry - self.stop_loss) / self.entry * 100

    @property
    def is_actionable(self) -> bool:
        """Cheap pre-filter so the LLM is never called on a non-trade."""
        if self.action is SignalAction.HOLD:
            return False
        return self.risk_reward is not None and self.risk_reward >= 1.0

    @property
    def score_total(self) -> float:
        return self.score.total if self.score else 0.0


class AgentAssessment(Base):
    """Structured verdict from one specialist agent.

    ``confidence`` is the agent's own calibration and is clamped server-side:
    an autonomous system claiming 99% certainty about a trade is a symptom, not
    an edge.
    """

    role: AgentRole
    verdict: AgentVerdict
    confidence: Probability
    summary: str = Field(min_length=1, max_length=600)
    rationale: list[Rationale] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list, max_length=12)
    risk_level: RiskLevel = RiskLevel.LOW
    suggested_adjustments: list[str] = Field(default_factory=list, max_length=8)
    latency_ms: int | None = None
    model: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    degraded: bool = Field(
        default=False,
        description="True when produced by the rule-based fallback rather than an LLM.",
    )

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return min(value, MAX_AGENT_CONFIDENCE)

    @property
    def is_approve(self) -> bool:
        return self.verdict is AgentVerdict.APPROVE


class AgentState(Base):
    """State passed between nodes of the agent graph (LangGraph state)."""

    symbol: str
    timeframe: Timeframe = Timeframe.H1
    signal: Signal | None = None
    market_snapshot: dict | None = None
    portfolio: dict | None = None
    strategy_metrics: dict | None = None
    news: list[dict] = Field(default_factory=list)
    assessments: dict[str, AgentAssessment] = Field(default_factory=dict)
    loop_count: int = 0
    errors: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)


class TradeProposal(Base):
    """The decision agent's output. A proposal, never an instruction."""

    symbol: str
    action: SignalAction
    confidence: Probability
    entry: Price
    stop_loss: Price
    take_profit: Price
    position_size_pct: float = Field(gt=0, le=100)
    rationale: list[Rationale] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list, max_length=12)
    market_regime: str | None = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    strategy: str | None = None
    confidence_breakdown: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, value: float) -> float:
        return min(value, MAX_AGENT_CONFIDENCE)

    @property
    def risk_reward(self) -> float:
        risk = abs(self.entry - self.stop_loss)
        if risk <= 0:
            return 0.0
        return abs(self.take_profit - self.entry) / risk

    @property
    def fingerprint(self) -> str:
        """Identity of the proposal's economics, for loop detection."""
        return (
            f"{self.symbol}:{self.action.value}:{self.entry:.4f}:{self.stop_loss:.4f}:{self.take_profit:.4f}"
        )
