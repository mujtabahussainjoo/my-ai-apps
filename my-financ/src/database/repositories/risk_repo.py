"""Risk, backtest and strategy-status persistence.

``RiskRepository.record_assessment`` writes the assessment *and* one event row
per check in a single transaction. Splitting them would allow an assessment
with no events - which is exactly the state that makes a rejection impossible
to explain after the fact.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.database.base import utcnow
from src.database.models import (
    BacktestRun,
    BacktestTrade,
    CircuitBreakerEvent,
    RiskAssessment,
    RiskEvent,
    StrategyStatus,
    SystemEvent,
)
from src.database.repositories import mappers
from src.schemas.risk import RiskAssessment as AssessmentSchema

logger = get_logger(__name__)


class RiskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_assessment(
        self,
        assessment: AssessmentSchema,
        *,
        symbol: str,
        side: str,
        mode: str,
        requested_quantity: float,
        order_id: str | None = None,
        signal_id: str | None = None,
        strategy: str | None = None,
        equity: float | None = None,
        drawdown: float | None = None,
    ) -> RiskAssessment:
        payload = mappers.assessment_to_row(
            assessment,
            symbol=symbol,
            side=side,
            mode=mode,
            requested_quantity=requested_quantity,
            order_id=order_id,
            signal_id=signal_id,
            strategy=strategy,
            equity=equity,
            drawdown=drawdown,
        )
        row = RiskAssessment(**payload)
        self.session.add(row)
        self.session.flush()

        events = mappers.risk_events_from_assessment(assessment, row.id)
        if events:
            self.session.execute(RiskEvent.__table__.insert(), events)
        return row

    def get_assessment(self, assessment_id: str) -> RiskAssessment | None:
        return self.session.get(RiskAssessment, assessment_id)

    def assessments_for_symbol(self, symbol: str, limit: int = 20) -> list[RiskAssessment]:
        stmt = (
            select(RiskAssessment)
            .where(RiskAssessment.symbol == symbol)
            .order_by(RiskAssessment.assessed_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def assessments_for_order(self, order_id: str) -> list[RiskAssessment]:
        return list(
            self.session.scalars(
                select(RiskAssessment)
                .where(RiskAssessment.order_id == order_id)
                .order_by(RiskAssessment.assessed_at)
            )
        )

    def failed_checks(self, limit: int = 100, since: datetime | None = None) -> list[RiskEvent]:
        stmt = (
            select(RiskEvent)
            .where(RiskEvent.passed.is_(False))
            .order_by(RiskEvent.created_at.desc())
            .limit(limit)
        )
        if since:
            stmt = stmt.where(RiskEvent.created_at >= since)
        return list(self.session.scalars(stmt))

    def rejection_rate(self, since: datetime) -> float:
        total = int(
            self.session.scalar(
                select(func.count()).select_from(RiskAssessment).where(
                    RiskAssessment.assessed_at >= since
                )
            )
            or 0
        )
        if total == 0:
            return 0.0
        rejected = int(
            self.session.scalar(
                select(func.count())
                .select_from(RiskAssessment)
                .where(
                    RiskAssessment.assessed_at >= since,
                    RiskAssessment.verdict.in_(["rejected", "halted"]),
                )
            )
            or 0
        )
        return rejected / total

    def log_breaker(
        self,
        breaker: str,
        action: str,
        reason: str,
        *,
        triggered_by: str | None = None,
        value: float | None = None,
        threshold: float | None = None,
        mode: str | None = None,
    ) -> CircuitBreakerEvent:
        row = CircuitBreakerEvent(
            breaker=breaker,
            action=action,
            reason=reason,
            triggered_by=triggered_by,
            value=value,
            threshold=threshold,
            mode=mode,
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def breaker_history(self, breaker: str | None = None, limit: int = 50) -> list[CircuitBreakerEvent]:
        stmt = select(CircuitBreakerEvent).order_by(CircuitBreakerEvent.created_at.desc()).limit(limit)
        if breaker:
            stmt = stmt.where(CircuitBreakerEvent.breaker == breaker)
        return list(self.session.scalars(stmt))


class BacktestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, result, *, source: str = "synthetic", bar_count: int = 0) -> BacktestRun:
        """Store a run, replacing any previous run with the same id.

        ``run_id`` is derived from the inputs, so re-running the same backtest
        must overwrite rather than accumulate duplicates.
        """
        config = result.config
        existing = self.session.get(BacktestRun, result.run_id)
        payload = {
            "strategy": config.strategy,
            "symbol": config.symbol,
            "timeframe": config.timeframe.value,
            "source": source,
            "starting_equity": mappers.d(config.starting_equity),
            "config": {
                "strategy": config.strategy,
                "symbol": config.symbol,
                "timeframe": config.timeframe.value,
                "starting_equity": config.starting_equity,
                "risk_pct_per_trade": config.risk_pct_per_trade,
                "max_position_pct": config.max_position_pct,
                "max_open_positions": config.max_open_positions,
            },
            "metrics": result.metrics.model_dump(mode="json"),
            "equity_curve": result.equity_curve,
            "signals_generated": result.signals_generated,
            "trade_count": len(result.trades),
            "bar_count": bar_count,
            "completed_at": utcnow(),
        }

        if existing is not None:
            for key, value in payload.items():
                setattr(existing, key, value)
            self.session.execute(
                BacktestTrade.__table__.delete().where(BacktestTrade.run_id == result.run_id)
            )
            row = existing
        else:
            row = BacktestRun(run_id=result.run_id, created_at=utcnow(), **payload)
            self.session.add(row)
        self.session.flush()

        if result.trades:
            self.session.execute(
                BacktestTrade.__table__.insert(),
                [
                    {
                        "run_id": result.run_id,
                        "symbol": t.symbol,
                        "side": t.side.value,
                        "quantity": mappers.d(t.quantity),
                        "entry_price": mappers.d(t.entry_price),
                        "exit_price": mappers.d(t.exit_price or t.entry_price),
                        "entry_time": mappers.dt(t.entry_time),
                        "exit_time": mappers.dt(t.exit_time or t.entry_time),
                        "gross_pnl_usd": mappers.d(t.gross_pnl_usd),
                        "fees_usd": mappers.d(t.fees_usd),
                        "pnl_usd": mappers.d(t.pnl_usd),
                        "risk_multiple": mappers.opt_d(t.risk_multiple),
                        "exit_reason": t.exit_reason,
                    }
                    for t in result.trades
                ],
            )
        self.session.flush()
        logger.info("backtest_saved", run_id=result.run_id, trades=len(result.trades))
        return row

    def get(self, run_id: str) -> BacktestRun | None:
        return self.session.get(BacktestRun, run_id)

    def latest_for(self, strategy: str) -> BacktestRun | None:
        return self.session.scalar(
            select(BacktestRun)
            .where(BacktestRun.strategy == strategy)
            .order_by(BacktestRun.completed_at.desc())
            .limit(1)
        )

    def list_runs(self, strategy: str | None = None, limit: int = 20) -> list[BacktestRun]:
        stmt = select(BacktestRun).order_by(BacktestRun.completed_at.desc()).limit(limit)
        if strategy:
            stmt = stmt.where(BacktestRun.strategy == strategy)
        return list(self.session.scalars(stmt))

    def trades_for(self, run_id: str) -> list[BacktestTrade]:
        return list(
            self.session.scalars(
                select(BacktestTrade)
                .where(BacktestTrade.run_id == run_id)
                .order_by(BacktestTrade.entry_time)
            )
        )


class StrategyStatusRepository:
    """The promotion gate. Execution reads ``qualified`` from here."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def set(
        self,
        strategy: str,
        status: str,
        *,
        qualified: bool,
        metrics: dict | None = None,
        qualification: dict | None = None,
        blocking_reason: str | None = None,
        version: str = "1.0",
    ) -> StrategyStatus:
        row = self.session.get(StrategyStatus, strategy)
        if row is None:
            row = StrategyStatus(strategy=strategy)
            self.session.add(row)
        row.status = status
        row.qualified = qualified
        row.metrics = metrics
        row.qualification = qualification
        row.blocking_reason = blocking_reason
        row.version = version
        if qualified and row.promoted_at is None:
            row.promoted_at = utcnow()
        if not qualified:
            row.promoted_at = None
        self.session.flush()
        return row

    def get(self, strategy: str) -> StrategyStatus | None:
        return self.session.get(StrategyStatus, strategy)

    def is_qualified(self, strategy: str | None) -> bool:
        """Whether execution may trade this strategy.

        An unknown strategy is not qualified. Absent evidence must not read as
        permission.
        """
        if not strategy:
            return False
        row = self.session.get(StrategyStatus, strategy)
        return bool(row and row.qualified)

    def qualified_strategies(self) -> list[str]:
        return list(
            self.session.scalars(
                select(StrategyStatus.strategy).where(StrategyStatus.qualified.is_(True))
            )
        )

    def all(self) -> list[StrategyStatus]:
        return list(self.session.scalars(select(StrategyStatus).order_by(StrategyStatus.strategy)))


class SystemEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def log(
        self, component: str, event: str, message: str, *, level: str = "info", context: dict | None = None
    ) -> SystemEvent:
        row = SystemEvent(
            component=component, event=event, message=message, level=level, context=context,
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def recent(self, limit: int = 50, level: str | None = None) -> list[SystemEvent]:
        stmt = select(SystemEvent).order_by(SystemEvent.created_at.desc()).limit(limit)
        if level:
            stmt = stmt.where(SystemEvent.level == level)
        return list(self.session.scalars(stmt))