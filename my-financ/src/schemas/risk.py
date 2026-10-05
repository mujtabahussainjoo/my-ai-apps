"""Risk schemas: guardrail results, sizing, and the strategy qualification gate."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, computed_field

from src.core.enums import RiskLevel, RiskVerdict, Severity, StrategyStatus
from src.schemas.base import Base, PositiveFloat, Price, Probability, utcnow


class RiskCheck(Base):
    """Outcome of a single guardrail.

    ``observed`` and ``limit`` are kept so a rejection can be explained
    numerically ("exposure 47% > limit 40%") rather than as prose.
    """

    rule: str
    passed: bool
    message: str = ""
    severity: Severity = Severity.WARNING
    observed: float | None = None
    limit: float | None = None
    unit: str | None = None

    @property
    def is_blocking(self) -> bool:
        return not self.passed and self.severity in (Severity.WARNING, Severity.CRITICAL)


class RiskAssessment(Base):
    """Verdict from the hard risk engine.

    Execution depends on this object alone. Agent output, user requests, and
    MCP tool calls are all inputs — none of them is an authorisation.
    """

    verdict: RiskVerdict
    approved_quantity: float = Field(default=0.0, ge=0)
    approved_notional_usd: float = Field(default=0.0, ge=0)
    approved_risk_usd: float = Field(default=0.0, ge=0)
    checks: list[RiskCheck] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    adjusted_stop_loss: float | None = None
    adjusted_take_profit: float | None = None
    leverage: float = Field(default=1.0, ge=1.0)
    requires_approval: bool = False
    assessed_at: datetime = Field(default_factory=utcnow)
    engine_version: str = "1.0"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allowed(self) -> bool:
        return self.verdict in (RiskVerdict.APPROVED, RiskVerdict.APPROVED_REDUCED)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed_rules(self) -> list[str]:
        return [c.rule for c in self.checks if not c.passed]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reasons(self) -> list[str]:
        return [c.message for c in self.checks if not c.passed and c.message]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_reduced(self) -> bool:
        return self.verdict is RiskVerdict.APPROVED_REDUCED


class RiskEvent(Base):
    """Audit record. Every guardrail hit is persisted, pass or fail."""

    id: str
    rule: str
    severity: Severity
    symbol: str
    message: str
    passed: bool = False
    observed: float | None = None
    limit: float | None = None
    context: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class CircuitBreakerState(Base):
    """Aggregate breaker status surfaced to the dashboard and health check."""

    kill_switch_engaged: bool = False
    kill_switch_reason: str | None = None
    daily_loss_halted: bool = False
    drawdown_halted: bool = False
    trading_enabled: bool = True
    halt_reason: str | None = None
    daily_pnl_usd: float = 0.0
    daily_loss_limit_usd: float = 0.0
    current_drawdown_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    as_of: datetime = Field(default_factory=utcnow)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def halted(self) -> bool:
        return self.kill_switch_engaged or self.daily_loss_halted or self.drawdown_halted


class PositionSizeRequest(Base):
    equity_usd: PositiveFloat
    entry_price: Price
    stop_loss: Price
    risk_pct: float | None = Field(default=None, gt=0, le=100)
    max_risk_usd: float | None = Field(default=None, gt=0)
    max_position_pct: float | None = Field(default=None, gt=0, le=100)


class PositionSizeResult(Base):
    """Quantity derived from a fixed-fractional risk budget.

    ``capped_by`` records which limit bound the result, so the dashboard can
    show *why* a trade was smaller than the signal asked for.
    """

    quantity: float = Field(gt=0)
    notional_usd: PositiveFloat
    risk_usd: PositiveFloat
    risk_pct: float = Field(ge=0)
    stop_distance_pct: float = Field(ge=0)
    capped_by: str
    unrounded_quantity: float | None = None


# ── Qualification gate (Workflow.md §5) ─────────────────────────────────────
class QualificationCriterion(Base):
    name: str
    required: float
    observed: float | None
    passed: bool
    comparator: Literal[">=", "<="] = ">="
    unit: str = ""
    #: Human-readable verdict, e.g. "win_rate 0.52 vs required >= 0.7".
    #: Computed at evaluation time; without it a failed criterion reports only
    #: its name, which is not actionable.
    message: str = ""


class QualificationResult(Base):
    """Verdict of the promotion gate.

    Win rate is necessary but not sufficient: a 70% win rate with a payoff
    ratio below 1 loses money, so profit factor, drawdown, sample size and R:R
    are evaluated independently and all must pass.
    """

    strategy: str
    status: StrategyStatus
    qualified: bool = False
    criteria: list[QualificationCriterion] = Field(default_factory=list)
    failed_criteria: list[str] = Field(default_factory=list)
    blocking_reason: str | None = None
    paper_days: float = 0.0
    paper_trades: int = 0
    evaluated_at: datetime = Field(default_factory=utcnow)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score_passed(self) -> int:
        return sum(1 for c in self.criteria if c.passed)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score_total(self) -> int:
        return len(self.criteria)


class StrategyMetrics(Base):
    """Per-strategy performance snapshot feeding the registry UI."""

    strategy: str
    status: StrategyStatus
    win_rate: Probability = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    sharpe_ratio: float = 0.0
    average_risk_reward: float = 0.0
    expectancy_usd: float = 0.0
    paper_win_rate: Probability | None = None
    paper_trades: int = 0
    paper_days: float = 0.0
    qualified: bool = False
    last_backtest_at: datetime | None = None
    last_updated: datetime = Field(default_factory=utcnow)