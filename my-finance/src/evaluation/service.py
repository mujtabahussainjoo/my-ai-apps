"""Qualification from persisted evidence, separated from operator promotion."""

from datetime import UTC, datetime

from sqlalchemy import select

from src.core.config import get_settings
from src.database.models.audit import BacktestRun
from src.database.repositories import PaperPerformanceRepository
from src.evaluation.qualification import PaperTrackRecord, QualificationThresholds, qualify
from src.schemas.portfolio import PerformanceMetrics


def evaluate_strategy(session, strategy, settings=None):
    settings = settings or get_settings()
    runs = list(
        session.scalars(
            select(BacktestRun)
            .where(BacktestRun.strategy == strategy)
            .order_by(BacktestRun.completed_at.desc())
        )
    )
    # Synthetic data is useful to exercise software, never to qualify trading.
    runs = [run for run in runs if run.source not in ("synthetic", "mock")]
    training = next((run for run in runs if run.config.get("label") == "in_sample"), None)
    oos = next(
        (
            run
            for run in runs
            if training is not None
            and run.config.get("label") == "out_of_sample"
            and run.config.get("evaluation_id") == training.config.get("evaluation_id")
        ),
        None,
    )
    if training is None:
        raise ValueError(
            "no recorded backtest with real in-sample evidence; run an evaluation backtest first"
        )
    if oos is None:
        raise ValueError("no matching out-of-sample backtest evidence")
    if training.symbol != oos.symbol or training.timeframe != oos.timeframe:
        raise ValueError("out-of-sample evidence is for a different market")
    if (
        not training.config.get("end")
        or not oos.config.get("start")
        or training.config["end"] >= oos.config["start"]
    ):
        raise ValueError("training and out-of-sample windows must not overlap")

    def metrics(payload):
        payload = dict(payload)
        if payload.get("profit_factor") is None:
            payload["profit_factor"] = (
                float("inf")
                if payload.get("gross_profit_usd", 0) > 0 and not payload.get("gross_loss_usd")
                else 0
            )
        return PerformanceMetrics.model_validate(payload)

    backtest = metrics(training.metrics)
    out_of_sample = metrics(oos.metrics)
    row = PaperPerformanceRepository(session).refresh(strategy)
    paper = PaperTrackRecord(
        trades=int(row.trades),
        win_rate=float(row.win_rate),
        profit_factor=float(row.profit_factor),
        max_drawdown_pct=float(row.max_drawdown_pct),
        days_active=float(row.days_active),
        starting_balance=float(row.starting_balance),
        ending_balance=float(row.ending_balance),
    )
    thresholds = QualificationThresholds.from_settings(settings)
    result = qualify(strategy, backtest, out_of_sample=out_of_sample, paper=paper, thresholds=thresholds)
    # Paper eligibility requires every non-paper criterion and adequate sample.
    backtest_ready = all(
        c.passed for c in result.criteria if not c.name.startswith("paper_")
    ) and backtest.total_trades >= max(thresholds.min_trades, 30)
    evidence = {
        "in_sample_run": training.run_id,
        "out_of_sample_run": oos.run_id,
        "report": result.model_dump(mode="json"),
        "evaluated_at": datetime.now(UTC).isoformat(),
    }
    return result, backtest_ready, evidence
