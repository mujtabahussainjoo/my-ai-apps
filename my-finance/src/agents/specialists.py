"""Specialist reviews combine reproducible checks with optional model context."""

from src.core.enums import AgentRole, AgentVerdict, RiskLevel, SignalAction
from src.schemas.signal import AgentAssessment, AgentState


def baseline(role: AgentRole, state: AgentState) -> AgentAssessment:
    signal = state.signal
    approved = signal is not None and signal.is_actionable
    concerns = []
    summary = "Deterministic signal has valid protective levels"
    verdict = AgentVerdict.APPROVE if approved else AgentVerdict.REJECT
    confidence = min(signal.confidence, 0.85) if approved else 0
    if role is AgentRole.TECHNICAL and signal is not None:
        if signal.action is SignalAction.BUY:
            approved = (
                signal.stop_loss is not None
                and signal.take_profit is not None
                and signal.stop_loss < signal.entry < signal.take_profit
            )
        elif signal.action is SignalAction.SELL:
            approved = (
                signal.stop_loss is not None
                and signal.take_profit is not None
                and signal.take_profit < signal.entry < signal.stop_loss
            )
        else:
            approved = False
        verdict = AgentVerdict.APPROVE if approved else AgentVerdict.REJECT
        summary = "Protective level geometry is valid" if approved else "Protective levels are invalid"
    elif role is AgentRole.MARKET:
        last = (state.market_snapshot or {}).get("last")
        if not last or last <= 0:
            verdict, confidence, summary = AgentVerdict.ABSTAIN, 0, "Market quote unavailable"
        else:
            summary = "A market quote is available; freshness is checked by the hard risk engine"
    elif role is AgentRole.SENTIMENT:
        if not state.news:
            verdict, confidence, summary = (
                AgentVerdict.ABSTAIN,
                0.5,
                "No recent news evidence; sentiment is unknown",
            )
            concerns = ["No news coverage"]
        else:
            summary = f"{len(state.news)} timestamped news items available for review"
    elif role is AgentRole.RISK:
        portfolio = state.portfolio or {}
        if portfolio.get("equity_usd", 0) <= 0:
            verdict, confidence, summary = AgentVerdict.REJECT, 0, "No usable equity for sizing"
        else:
            summary = "Portfolio supplied; hard risk engine retains sizing and final admission authority"
    return AgentAssessment(
        role=role,
        verdict=verdict,
        confidence=confidence,
        summary=summary,
        concerns=concerns,
        risk_level=RiskLevel.MEDIUM,
        degraded=True,
        model="deterministic-review",
    )
