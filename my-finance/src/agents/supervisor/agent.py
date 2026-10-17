"""A bounded LangGraph review pipeline. It produces advice, never an order."""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.specialists import baseline
from src.core.config import Settings, get_settings
from src.core.constants import AGENT_SCORE_WEIGHTS, MIN_AGENT_CONFIDENCE_TO_TRADE
from src.core.enums import AgentRole, AgentVerdict, RiskLevel
from src.core.security import sanitize_untrusted
from src.llm.client import ReviewClient
from src.schemas.signal import AgentAssessment, AgentState, Signal


class GraphState(TypedDict):
    analysis: AgentState


class Supervisor:
    def __init__(self, settings: Settings | None = None, *, reviewer=None):
        self.settings = settings or get_settings()
        self.reviewer = reviewer or ReviewClient(self.settings)
        graph = StateGraph(GraphState)
        previous = START
        for role in (AgentRole.MARKET, AgentRole.TECHNICAL, AgentRole.SENTIMENT, AgentRole.RISK):
            graph.add_node(role.value, self._node(role))
            graph.add_edge(previous, role.value)
            previous = role.value
        graph.add_node("decision", self._decision)
        graph.add_edge(previous, "decision")
        graph.add_edge("decision", END)
        self.graph = graph.compile()

    def _node(self, role):
        def run(graph_state):
            state = graph_state["analysis"].model_copy(deep=True)
            fallback = baseline(role, state)
            context = {
                "signal": state.signal.model_dump(mode="json") if state.signal else None,
                "market": state.market_snapshot,
                "portfolio": state.portfolio,
                "strategy_metrics": state.strategy_metrics,
                "news": state.news,
            }
            assessment = self.reviewer.review(role, context, fallback)
            assessment = AgentAssessment.model_validate(assessment)
            if assessment.role is not role:
                raise ValueError("reviewer changed its specialist role")
            state.assessments[role.value] = assessment
            state.trace.append(role.value)
            return {"analysis": state}

        return run

    def _decision(self, graph_state):
        state = graph_state["analysis"].model_copy(deep=True)
        mandatory = [state.assessments[r] for r in ("market", "technical", "risk")]
        confidence = sum(
            state.assessments[name].confidence * weight for name, weight in AGENT_SCORE_WEIGHTS.items()
        )
        allowed = (
            all(a.is_approve for a in mandatory)
            and not any(a.verdict is AgentVerdict.REJECT for a in state.assessments.values())
            and confidence >= MIN_AGENT_CONFIDENCE_TO_TRADE
        )
        degraded = any(a.degraded for a in state.assessments.values())
        if self.settings.trading_mode in ("testnet", "live") and degraded:
            allowed = False
        state.assessments["decision"] = AgentAssessment(
            role=AgentRole.DECISION,
            verdict=AgentVerdict.APPROVE if allowed else AgentVerdict.REJECT,
            confidence=confidence,
            summary="Specialist reviews agree; hard risk checks still required"
            if allowed
            else "Specialist review did not pass",
            concerns=[a.summary for a in state.assessments.values() if not a.is_approve][:12],
            degraded=degraded,
            risk_level=RiskLevel.MEDIUM if allowed else RiskLevel.HIGH,
        )
        state.trace.append("decision")
        return {"analysis": state}

    def analyse(
        self, signal: Signal, *, ticker=None, portfolio=None, news=None, strategy_metrics=None, session=None
    ) -> AgentState:
        state = AgentState(
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            signal=signal,
            market_snapshot=ticker.model_dump(mode="json") if ticker is not None else None,
            portfolio=portfolio.model_dump(mode="json") if portfolio is not None else None,
            strategy_metrics=strategy_metrics,
            news=news or [],
            trace=["supervisor"],
        )
        state.assessments["supervisor"] = AgentAssessment(
            role=AgentRole.SUPERVISOR,
            verdict=AgentVerdict.ABSTAIN,
            confidence=0,
            summary="Review pipeline started",
        )
        try:
            for item in state.news:
                for value in item.values():
                    if isinstance(value, str):
                        sanitize_untrusted(value)
            output = self.graph.invoke({"analysis": state}, config={"recursion_limit": 8})["analysis"]
            # The model never receives authority to alter economic fields.
            if output.signal != signal:
                raise ValueError("analysis changed the deterministic signal")
        except Exception as exc:
            output = state.model_copy(deep=True)
            output.errors.append(type(exc).__name__)
            output.assessments["decision"] = AgentAssessment(
                role=AgentRole.DECISION,
                verdict=AgentVerdict.REJECT,
                confidence=0,
                summary="Review pipeline failed closed",
                risk_level=RiskLevel.HIGH,
                degraded=True,
            )
        if session is not None:
            from src.database.repositories.agent_repo import AgentRepository

            AgentRepository(session).record(output)
        return output

    @staticmethod
    def approved(state: AgentState) -> bool:
        decision = state.assessments.get("decision")
        return decision is not None and decision.is_approve and not state.errors
