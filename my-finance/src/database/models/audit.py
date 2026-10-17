"""Audit tables: risk assessments, risk events, backtests, strategy status, agents.

Risk events are the most important table in the schema. They are written for
*every* check on *every* order, including the ones that pass, because the
question "what did the system know when it traded?" can only be answered from a
complete record.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.database.base import (
    BIGINT_PK,
    MONEY,
    PRICE,
    QUANTITY,
    Base,
    JSONType,
    TimestampMixin,
    new_id,
)


class RiskAssessment(Base):
    """The decision record for one order attempt."""

    __tablename__ = "risk_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    signal_id: Mapped[str | None] = mapped_column(String(36))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy: Mapped[str | None] = mapped_column(String(64))

    verdict: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    requested_quantity: Mapped[float] = mapped_column(QUANTITY, nullable=False)
    approved_quantity: Mapped[float] = mapped_column(QUANTITY, default=0.0, nullable=False)
    approved_notional_usd: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    approved_risk_usd: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    leverage: Mapped[float] = mapped_column(MONEY, default=1.0, nullable=False)

    #: Every individual check, pass or fail, with its observed value and limit.
    checks: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    equity_at_assessment: Mapped[float | None] = mapped_column(MONEY)
    drawdown_at_assessment: Mapped[float | None] = mapped_column(MONEY)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), default="1.0", nullable=False)

    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="side_valid"),
        CheckConstraint(
            "verdict IN ('approved','approved_reduced','rejected','halted')", name="verdict_valid"
        ),
        Index("ix_risk_assessments_verdict_at", "verdict", "assessed_at"),
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    assessment_id: Mapped[str | None] = mapped_column(String(36), index=True)
    rule: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    observed: Mapped[float | None] = mapped_column(Float)
    limit_value: Mapped[float | None] = mapped_column(Float)
    #: Wide enough for the engine's longest label, "percent of equity"; see
    #: migration v003 for why truncating it is not an option.
    unit: Mapped[str | None] = mapped_column(String(32))
    context: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("passed IS NOT NULL", name="passed_not_null"),
        Index("ix_risk_events_rule_created", "rule", "created_at"),
        Index("ix_risk_events_unpassed", "passed", "created_at"),
    )


class CircuitBreakerEvent(Base):
    __tablename__ = "circuit_breaker_events"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    breaker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by: Mapped[str | None] = mapped_column(String(64))
    value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    mode: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("action IN ('engaged','released','reset')", name="action_valid"),
        Index("ix_breakers_breaker_at", "breaker", "created_at"),
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    #: Deterministic: the same inputs must map to the same id, so re-running a
    #: backtest updates its row instead of duplicating it.
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="synthetic", nullable=False)
    starting_equity: Mapped[float] = mapped_column(MONEY, default=10000.0, nullable=False)
    config: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    equity_curve: Mapped[list | None] = mapped_column(JSONType)
    signals_generated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bar_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_backtests_strategy_completed", "strategy", "completed_at"),)


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("backtest_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[float] = mapped_column(QUANTITY, nullable=False)
    entry_price: Mapped[float] = mapped_column(PRICE, nullable=False)
    exit_price: Mapped[float] = mapped_column(PRICE, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gross_pnl_usd: Mapped[float] = mapped_column(MONEY, nullable=False)
    fees_usd: Mapped[float] = mapped_column(MONEY, nullable=False)
    pnl_usd: Mapped[float] = mapped_column(MONEY, nullable=False)
    risk_multiple: Mapped[float | None] = mapped_column(MONEY)
    exit_reason: Mapped[str | None] = mapped_column(String(24))

    __table_args__ = (
        CheckConstraint("round(gross_pnl_usd - fees_usd, 6) = round(pnl_usd, 6)", name="pnl_is_net_of_fees"),
        Index("ix_bt_trades_run", "run_id"),
    )


class StrategyStatus(Base, TimestampMixin):
    """Current standing of one strategy. The gate the execution layer reads."""

    __tablename__ = "strategy_status"

    strategy: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    qualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(16), default="1.0", nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSONType)
    qualification: Mapped[dict | None] = mapped_column(JSONType)
    blocking_reason: Mapped[str | None] = mapped_column(Text)
    last_backtest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','backtesting','backtest_passed','paper_testing','paper','qualified','rejected','suspended','retired')",
            name="status_valid",
        ),
    )


class AgentSession(Base, TimestampMixin):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(64))
    #: 'chat', 'analysis', 'trade_proposal'. Chat never mutates the portfolio.
    session_type: Mapped[str] = mapped_column(String(24), default="chat", nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    openai_thread_id: Mapped[str | None] = mapped_column(String(64))
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)

    __table_args__ = (
        CheckConstraint("session_type IN ('chat','analysis','trade_proposal')", name="session_type_valid"),
        Index("ix_agent_sessions_agent", "agent"),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Structured payload when the agent returned JSON, e.g. a TradeProposal.
    structured: Mapped[dict | None] = mapped_column(JSONType)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(MONEY, default=0.0, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    #: True when the prompt was rejected by the injection filter.
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system','tool')", name="role_valid"),
        Index("ix_agent_messages_session", "session_id", "created_at"),
    )


class SystemEvent(Base):
    """Operational log: starts, stops, config changes, errors."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("level IN ('debug','info','warning','error','critical')", name="level_valid"),
        Index("ix_system_events_event_at", "event", "created_at"),
    )
