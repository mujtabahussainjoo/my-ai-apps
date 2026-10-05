"""Performance metrics computed from closed trades.

Every function here is arithmetic over realised trades. None of it consults an
LLM, and none of it smooths a bad result: a 60% win rate with a payoff ratio of
0.8 must come out as a losing system, because that is what it is.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from src.schemas.portfolio import PerformanceMetrics
from src.schemas.trade import Trade


def win_rate(trades: Sequence[Trade]) -> float:
    """Fraction of closed trades with positive net P&L.

    Break-even trades are excluded from the denominator: counting a 0.00 trade
    as a loss understates a strategy whose real problem is cost, not accuracy.
    """
    decided = [t for t in trades if t.pnl_usd != 0]
    if not decided:
        return 0.0
    return sum(1 for t in decided if t.pnl_usd > 0) / len(decided)


def gross_profit_loss(trades: Sequence[Trade]) -> tuple[float, float]:
    wins = sum(t.pnl_usd for t in trades if t.pnl_usd > 0)
    losses = sum(abs(t.pnl_usd) for t in trades if t.pnl_usd < 0)
    return wins, losses


def profit_factor(trades: Sequence[Trade]) -> float:
    """Gross profit / gross loss.

    Returns ``inf`` when there are no losses at all, which the qualification
    gate treats cautiously rather than as automatically excellent — a strategy
    with one trade cannot have a meaningful profit factor.
    """
    wins, losses = gross_profit_loss(trades)
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def expectancy_usd(trades: Sequence[Trade]) -> float:
    """Mean net P&L per trade."""
    return float(np.mean([t.pnl_usd for t in trades])) if trades else 0.0


def expectancy_r(trades: Sequence[Trade]) -> float:
    """Mean P&L in units of initial risk (R).

    This is the most transferable expectancy measure: it says how much of the
    risk taken was returned, independent of position sizing.
    """
    values = [t.risk_multiple for t in trades if t.risk_multiple is not None]
    return float(np.mean(values)) if values else 0.0


def payoff_ratio(trades: Sequence[Trade]) -> float:
    """Average win / average loss."""
    wins = [t.pnl_usd for t in trades if t.pnl_usd > 0]
    losses = [abs(t.pnl_usd) for t in trades if t.pnl_usd < 0]
    if not wins or not losses:
        return 0.0
    return float(np.mean(wins) / np.mean(np.abs(losses)))


def equity_curve(trades: Sequence[Trade], starting_equity: float) -> list[float]:
    """Running equity, starting from ``starting_equity``.

    Costs are already inside ``trade.pnl_usd``, so this must not subtract fees
    again.
    """
    equity = starting_equity
    curve = [equity]
    for trade in sorted(trades, key=lambda t: t.exit_time or t.entry_time):
        equity += trade.pnl_usd
        curve.append(equity)
    return curve


def max_drawdown_pct(curve: Sequence[float]) -> float:
    """Largest peak-to-trough decline as a percent of the peak.

    Computed on the equity curve rather than per-trade so intra-trade
    drawdown is not counted as a realised loss.
    """
    if not curve:
        return 0.0
    peak = curve[0]
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100)
    return worst


def max_drawdown_usd(curve: Sequence[float]) -> float:
    if not curve:
        return 0.0
    peak = curve[0]
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


def max_consecutive(trades: Sequence[Trade], winning: bool) -> int:
    """Longest run of wins or losses in entry order."""
    longest = current = 0
    for trade in trades:
        if (trade.pnl_usd > 0) is winning:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def sharpe_ratio(trades: Sequence[Trade], periods_per_year: int = 365) -> float:
    """Annualised Sharpe from per-trade returns.

    Uses trade returns rather than daily returns: this is a per-trade strategy
    evaluation, and annualising a per-trade series with a 365 factor would
    produce a meaningless number. The result is comparable *between strategies
    traded on the same symbols and timeframes*, which is how it is used.
    """
    returns = [t.pnl_pct for t in trades]
    if len(returns) < 2:
        return 0.0
    mean_return = float(np.mean(returns))
    std_return = float(np.std(returns, ddof=1))
    if std_return == 0:
        return 0.0
    return mean_return / std_return * float(np.sqrt(periods_per_year))


def sortino_ratio(trades: Sequence[Trade], periods_per_year: int = 365) -> float:
    """Like Sharpe but only downside deviation is penalised."""
    returns = [t.pnl_pct for t in trades]
    if len(returns) < 2:
        return 0.0
    mean_return = float(np.mean(returns))
    downside = [r for r in returns if r < 0]
    if not downside:
        return 0.0
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
    if downside_deviation == 0:
        return 0.0
    return mean_return / downside_deviation * float(np.sqrt(periods_per_year))


def calmar_ratio(curve: Sequence[float], periods_per_year: int = 365) -> float:
    """Annualised return divided by max drawdown percentage."""
    if len(curve) < 2:
        return 0.0
    drawdown = max_drawdown_pct(curve)
    if drawdown <= 0:
        return 0.0
    total_return = (curve[-1] - curve[0]) / curve[0] * 100 if curve[0] > 0 else 0.0
    return total_return / drawdown


def recovery_factor(curve: Sequence[float]) -> float:
    """Net profit / max drawdown. Above 1.0 means the gains exceed the pain."""
    if len(curve) < 2:
        return 0.0
    drawdown = max_drawdown_usd(curve)
    if drawdown <= 0:
        return 0.0
    return (curve[-1] - curve[0]) / drawdown


def average_risk_reward(trades: Sequence[Trade]) -> float:
    """Mean *realised* R-multiple achieved per trade."""
    values = [t.risk_multiple for t in trades if t.risk_multiple is not None]
    return float(np.mean(values)) if values else 0.0


def planned_risk_reward(trades: Sequence[Trade]) -> float:
    """Mean *planned* reward-to-risk of the originating signals.

    Kept separate from :func:`average_risk_reward` on purpose: the qualification
    gate's "R/R >= 1:2" requirement describes the setup the strategy takes, not
    the R it ended up realising. Conflating them would make a strategy that
    consistently targets 3R fail the gate for realising 1.16R.
    """
    values = [t.planned_risk_reward for t in trades if t.planned_risk_reward is not None]
    return float(np.mean(values)) if values else 0.0


def average_trade_duration(trades: Sequence[Trade]) -> float:
    durations = [t.duration_seconds for t in trades if t.duration_seconds is not None]
    return float(np.mean(durations)) if durations else 0.0


def win_rate_confidence_interval(win_count: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a win rate.

    This is the guardrail against the headline 70% claim: a strategy with 7
    wins out of 10 has a 70% observed rate and a confidence interval spanning
    roughly 40-89%. Reporting the interval alongside the rate is what makes the
    claim defensible rather than a small-sample artefact.
    """
    if total <= 0:
        return 0.0, 0.0
    p = win_count / total
    denominator = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denominator
    margin = (
        z * np.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denominator
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def compute_metrics(
    trades: Sequence[Trade],
    *,
    starting_equity: float = 10_000.0,
    include_curve: bool = True,
) -> PerformanceMetrics:
    """Full metric set for a closed-trade list."""
    ordered = sorted(trades, key=lambda t: t.exit_time or t.entry_time)
    wins, losses = gross_profit_loss(ordered)
    winning = [t for t in ordered if t.pnl_usd > 0]
    losing = [t for t in ordered if t.pnl_usd < 0]
    breakeven = [t for t in ordered if t.pnl_usd == 0]

    curve = equity_curve(ordered, starting_equity) if include_curve else []
    net_profit = sum(t.pnl_usd for t in ordered)

    interval_low, interval_high = win_rate_confidence_interval(len(winning), len(ordered))

    warning: str | None = None
    if len(ordered) < 30:
        warning = (
            f"only {len(ordered)} trades: metrics are statistically meaningless. "
            f"The {win_rate(ordered):.1%} win rate has a 95% confidence interval of "
            f"{interval_low:.1%}-{interval_high:.1%}."
        )
    elif len(ordered) < 100:
        warning = (
            f"{len(ordered)} trades is below the 100-trade minimum for a reliable "
            f"estimate; treat results as provisional."
        )

    return PerformanceMetrics(
        total_trades=len(ordered),
        winning_trades=len(winning),
        losing_trades=len(losing),
        breakeven_trades=len(breakeven),
        win_rate=win_rate(ordered),
        profit_factor=profit_factor(ordered),
        expectancy_usd=expectancy_usd(ordered),
        expectancy_r=expectancy_r(ordered),
        net_profit_usd=net_profit,
        net_profit_pct=(net_profit / starting_equity * 100) if starting_equity > 0 else 0.0,
        gross_profit_usd=wins,
        gross_loss_usd=losses,
        total_fees_usd=sum(t.fees_usd for t in ordered),
        average_win_usd=float(np.mean([t.pnl_usd for t in winning])) if winning else 0.0,
        average_loss_usd=float(np.mean([abs(t.pnl_usd) for t in losing])) if losing else 0.0,
        payoff_ratio=payoff_ratio(ordered),
        largest_win_usd=max((t.pnl_usd for t in winning), default=0.0),
        largest_loss_usd=min((t.pnl_usd for t in losing), default=0.0),
        max_drawdown_pct=max_drawdown_pct(curve) if curve else 0.0,
        max_drawdown_usd=max_drawdown_usd(curve) if curve else 0.0,
        max_consecutive_losses=max_consecutive(ordered, winning=False),
        max_consecutive_wins=max_consecutive(ordered, winning=True),
        sharpe_ratio=sharpe_ratio(ordered),
        sortino_ratio=sortino_ratio(ordered),
        calmar_ratio=calmar_ratio(curve) if curve else 0.0,
        average_risk_reward=average_risk_reward(ordered),
        planned_risk_reward=planned_risk_reward(ordered),
        average_trade_duration_seconds=average_trade_duration(ordered),
        recovery_factor=recovery_factor(curve) if curve else 0.0,
        equity_curve=curve,
        sample_size_warning=warning,
    )


def compare_runs(runs: dict[str, PerformanceMetrics]) -> list[dict[str, object]]:
    """Tabulate runs for the strategy registry view."""
    rows: list[dict[str, object]] = []
    for name, metrics in runs.items():
        rows.append(
            {
                "strategy": name,
                "trades": metrics.total_trades,
                "win_rate": round(metrics.win_rate * 100, 2),
                "profit_factor": round(metrics.profit_factor, 3)
                if np.isfinite(metrics.profit_factor)
                else None,
                "max_drawdown_pct": round(metrics.max_drawdown_pct, 2),
                "net_profit_usd": round(metrics.net_profit_usd, 2),
                "sharpe": round(metrics.sharpe_ratio, 3),
                "avg_rr": round(metrics.average_risk_reward, 3),
                "expectancy_r": round(metrics.expectancy_r, 4),
                "warning": metrics.sample_size_warning,
            }
        )
    return sorted(rows, key=lambda r: r["net_profit_usd"], reverse=True)  # type: ignore[arg-type,return-value]