"""The 70% qualification gate (Workflow.md §5).

The point of this module is to make a naive implementation of the requirement
impossible. A 70% win rate is necessary but nowhere near sufficient: winning 70
of 100 trades while losing more per loss than you win per win is a losing
system. So every criterion is evaluated independently and *all* of them must
pass.

Two extra safeguards beyond the spec:

- **Minimum sample size** and a reported **confidence interval**, so a 70% rate
  from 12 trades cannot be presented as evidence.
- **Paper-trading track record** as a separate requirement, because backtest
  performance and live behaviour routinely diverge.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.config import Settings, get_settings
from src.core.enums import StrategyStatus
from src.core.logging import get_logger
from src.evaluation.metrics import win_rate_confidence_interval
from src.schemas.portfolio import PerformanceMetrics
from src.schemas.risk import QualificationCriterion, QualificationResult

logger = get_logger(__name__)

#: Below this many trades no result is presented as evidence, regardless of how
#: good the other numbers look.
MINIMUM_VIABLE_SAMPLE = 30

#: Hard cap on how much the win-rate interval's lower bound may fall below the
#: target. If the interval is this wide, the result is inconclusive.
MAX_ACCEPTABLE_INTERVAL_WIDTH = 0.30


@dataclass(slots=True)
class PaperTrackRecord:
    """Live-forward evidence: what actually happened in paper trading."""

    trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    days_active: float = 0.0
    starting_balance: float = 10_000.0
    ending_balance: float = 10_000.0

    @property
    def return_pct(self) -> float:
        if self.starting_balance <= 0:
            return 0.0
        return (self.ending_balance - self.starting_balance) / self.starting_balance * 100


@dataclass(slots=True)
class QualificationThresholds:
    """Snapshot of the configured thresholds, so a result records what it was judged against."""

    min_win_rate: float
    min_profit_factor: float
    max_drawdown: float
    min_trades: int
    min_risk_reward: float
    min_paper_days: int
    min_paper_trades: int
    #: Backtest must stay profitable out-of-sample, not just in-sample.
    require_positive_oos: bool = True
    min_oos_trades: int = 30

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> QualificationThresholds:
        settings = settings or get_settings()
        return cls(
            min_win_rate=settings.qualify_min_win_rate,
            min_profit_factor=settings.qualify_min_profit_factor,
            max_drawdown=settings.qualify_max_drawdown,
            min_trades=settings.qualify_min_trades,
            min_risk_reward=settings.qualify_min_risk_reward,
            min_paper_days=settings.qualify_min_paper_days,
            min_paper_trades=settings.qualify_min_paper_trades,
        )


def evaluate_criterion(
    name: str,
    observed: float | None,
    required: float,
    *,
    comparator: str = ">=",
    unit: str = "",
) -> QualificationCriterion:
    if observed is None:
        passed = False
    elif comparator == ">=":
        passed = observed >= required
    elif comparator == ">":
        passed = observed > required
    elif comparator == "<=":
        passed = observed <= required
    else:  # pragma: no cover - guarded by the Literal type
        raise ValueError(f"unknown comparator {comparator}")

    if observed is None:
        message = f"{name}: no data available"
    elif comparator == ">=":
        message = f"{name} {observed:.4g} vs required >= {required:.4g}{(' ' + unit) if unit else ''}"
    else:
        message = f"{name} {observed:.4g} vs allowed <= {required:.4g}{(' ' + unit) if unit else ''}"

    if observed is not None and observed == float("inf"):
        message += " (no recorded losses; ratio is unbounded)"
        observed = None
    return QualificationCriterion(
        name=name,
        required=required,
        observed=observed,
        passed=passed,
        comparator=comparator,  # type: ignore[arg-type]
        unit=unit,
        message=message,
    )


def qualify(
    strategy: str,
    backtest: PerformanceMetrics,
    *,
    out_of_sample: PerformanceMetrics | None = None,
    paper: PaperTrackRecord | None = None,
    thresholds: QualificationThresholds | None = None,
    current_status: StrategyStatus = StrategyStatus.CANDIDATE,
) -> QualificationResult:
    """Decide whether a strategy may be promoted to trading.

    ``qualified`` is the only field execution is allowed to check. It is
    computed as "every criterion passed", never as a weighted score, so a
    strategy cannot average away a failed hard limit.
    """
    thresholds = thresholds or QualificationThresholds.from_settings()
    criteria: list[QualificationCriterion] = []

    # ── Sample size first: without it nothing else is meaningful ──
    criteria.append(
        evaluate_criterion(
            "backtest_trades",
            float(backtest.total_trades),
            float(max(thresholds.min_trades, MINIMUM_VIABLE_SAMPLE)),
            unit="trades",
        )
    )

    # ── Win rate, with an explicit statistical caveat ──
    criteria.append(
        evaluate_criterion("win_rate", backtest.win_rate, thresholds.min_win_rate, unit="(fraction)")
    )

    # ── The criteria that make 70% alone meaningless ──
    criteria.append(
        evaluate_criterion(
            "profit_factor",
            backtest.profit_factor if backtest.total_trades else None,
            thresholds.min_profit_factor,
        )
    )
    criteria.append(
        evaluate_criterion(
            "max_drawdown",
            backtest.max_drawdown_pct / 100 if backtest.total_trades else None,
            thresholds.max_drawdown,
            comparator="<=",
            unit="(fraction)",
        )
    )
    # Planned R:R of the setup — the ">= 1:2" line from the spec.
    criteria.append(
        evaluate_criterion(
            "planned_risk_reward",
            backtest.planned_risk_reward if backtest.total_trades else None,
            thresholds.min_risk_reward,
            unit="R (target vs stop)",
        )
    )
    # Realised expectancy — proof the planned R:R was actually captured.
    criteria.append(
        evaluate_criterion(
            "realised_expectancy",
            backtest.expectancy_r if backtest.total_trades else None,
            0.0,
            unit="R per trade (must be positive)",
            comparator=">",
        )
    )

    # ── Out-of-sample: the anti-data-leakage check (Workflow.md §20) ──
    if thresholds.require_positive_oos:
        if out_of_sample is None:
            criteria.append(
                evaluate_criterion("out_of_sample_trades", None, float(thresholds.min_oos_trades))
            )
            criteria.append(evaluate_criterion("out_of_sample_expectancy", None, 0.0, unit="R per trade"))
        else:
            criteria.append(
                evaluate_criterion(
                    "out_of_sample_trades",
                    float(out_of_sample.total_trades),
                    float(thresholds.min_oos_trades),
                )
            )
            criteria.append(
                evaluate_criterion(
                    "out_of_sample_expectancy",
                    out_of_sample.expectancy_r,
                    0.0,
                    unit="R per trade (must be positive)",
                    comparator=">",
                )
            )
            criteria.append(
                evaluate_criterion(
                    "out_of_sample_win_rate",
                    out_of_sample.win_rate,
                    thresholds.min_win_rate - 0.10,
                    unit="(fraction, 10pp tolerance)",
                )
            )

    # ── Paper trading: forward evidence ──
    criteria.append(
        evaluate_criterion(
            "paper_trades", float(paper.trades) if paper else None, float(thresholds.min_paper_trades)
        )
    )
    criteria.append(
        evaluate_criterion(
            "paper_days",
            float(paper.days_active) if paper else None,
            float(thresholds.min_paper_days),
            unit="days",
        )
    )
    if paper is not None:
        criteria.append(
            evaluate_criterion("paper_win_rate", paper.win_rate, thresholds.min_win_rate, unit="(fraction)")
        )
        criteria.append(
            evaluate_criterion("paper_profit_factor", paper.profit_factor, thresholds.min_profit_factor)
        )

    criteria.append(
        evaluate_criterion(
            "paper_drawdown",
            paper.max_drawdown_pct / 100 if paper else None,
            thresholds.max_drawdown,
            comparator="<=",
        )
    )
    criteria.append(
        evaluate_criterion("paper_return", paper.return_pct if paper else None, 0, comparator=">")
    )
    failed = [c for c in criteria if not c.passed]

    # Statistical honesty check: a wide interval around the win rate means the
    # result is inconclusive even if it nominally passes.
    interval_low, interval_high = win_rate_confidence_interval(backtest.winning_trades, backtest.total_trades)
    inconclusive_reason: str | None = None
    if (
        backtest.total_trades >= MINIMUM_VIABLE_SAMPLE
        and (interval_high - interval_low) > MAX_ACCEPTABLE_INTERVAL_WIDTH
    ):
        inconclusive_reason = (
            f"win-rate 95% interval is {interval_low:.1%}-{interval_high:.1%} "
            f"({(interval_high - interval_low):.0%} wide), so the result is "
            f"statistically inconclusive regardless of the point estimate"
        )
    elif backtest.total_trades < MINIMUM_VIABLE_SAMPLE:
        inconclusive_reason = (
            f"only {backtest.total_trades} trades — below the {MINIMUM_VIABLE_SAMPLE} "
            f"needed to make any win-rate claim"
        )

    qualified = not failed and inconclusive_reason is None

    blocking_reason: str | None = None
    if failed:
        blocking_reason = "failed: " + ", ".join(c.name for c in failed)
    elif inconclusive_reason:
        blocking_reason = inconclusive_reason

    status = (
        StrategyStatus.QUALIFIED
        if qualified
        else StrategyStatus.REJECTED
        if current_status in (StrategyStatus.REJECTED, StrategyStatus.RETIRED)
        else StrategyStatus.BACKTEST_PASSED
        if not failed
        else StrategyStatus.CANDIDATE
    )

    result = QualificationResult(
        strategy=strategy,
        status=status,
        qualified=qualified,
        criteria=criteria,
        failed_criteria=[c.name for c in failed],
        blocking_reason=blocking_reason,
        paper_days=paper.days_active if paper else 0.0,
        paper_trades=paper.trades if paper else 0,
    )

    logger.info(
        "strategy_qualification",
        strategy=strategy,
        qualified=qualified,
        passed=result.score_passed,
        total=result.score_total,
        win_rate=round(backtest.win_rate, 4),
        trades=backtest.total_trades,
        profit_factor=round(backtest.profit_factor, 3)
        if backtest.total_trades and backtest.profit_factor != float("inf")
        else None,
        blocking_reason=blocking_reason,
    )
    return result


def explain(result: QualificationResult) -> str:
    """Human-readable verdict for the API and dashboard."""
    lines = [
        f"Strategy: {result.strategy}",
        f"Verdict: {'QUALIFIED' if result.qualified else 'NOT QUALIFIED'}",
        f"Criteria passed: {result.score_passed}/{result.score_total}",
        "",
    ]
    for criterion in result.criteria:
        mark = "PASS" if criterion.passed else "FAIL"
        observed = "n/a" if criterion.observed is None else f"{criterion.observed:.4g}"
        lines.append(
            f"  [{mark}] {criterion.name}: {observed} {criterion.comparator} "
            f"{criterion.required:.4g}{(' ' + criterion.unit) if criterion.unit else ''}"
        )
    if result.blocking_reason:
        lines.extend(["", f"Blocking reason: {result.blocking_reason}"])
    lines.extend(
        [
            "",
            "Note: qualification means the strategy passed historical and "
            "forward testing. It is not a guarantee of future returns; crypto "
            "markets change regimes and live results diverge from backtests.",
        ]
    )
    return "\n".join(lines)
