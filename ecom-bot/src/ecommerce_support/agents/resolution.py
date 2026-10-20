"""Resolution Agent: decide whether an answer is enough, retry (bounded), or escalate (FR-024/048).

Framework-free. The agent never treats "an answer was produced" as resolution: a usable answer only
advances the flow to *asking the customer* (``AWAIT_CUSTOMER``). Insufficient answers trigger a
bounded retry with an alternative agent before the flow is escalated. The caller supplies the
customer's explicit ``resolved`` signal when one is available.
"""

from __future__ import annotations

from ecommerce_support.core.config import AgentsConfig
from ecommerce_support.schemas.agents import AgentState, ResolutionDecision
from ecommerce_support.schemas.enums import AgentName, ResolutionAction, ResolutionOutcome

_RETRYABLE_AGENTS = frozenset(
    {AgentName.ORDER, AgentName.PRODUCT, AgentName.POLICY, AgentName.ACCOUNT}
)


class ResolutionAgent:
    """Evaluates evidence sufficiency and chooses the next lifecycle action."""

    def __init__(self, config: AgentsConfig | None = None) -> None:
        self._config = config or AgentsConfig()

    def assess(self, state: AgentState, *, resolved: bool | None = None) -> ResolutionDecision:
        """Return the resolution decision for ``state``.

        ``resolved=True`` records success; ``resolved=False`` (customer says no) retries an
        alternative agent while attempts remain, otherwise escalates. With no explicit signal the
        answer's evidence is inspected.
        """
        sufficient = self._evidence_sufficient(state)

        if resolved is True:
            return ResolutionDecision(
                action=ResolutionAction.RESOLVED,
                reason="customer_confirmed",
                evidence_sufficient=sufficient,
                outcome=ResolutionOutcome.RESOLVED,
            )

        if resolved is False:
            return self._retry_or_escalate(state, reason="customer_reported_unresolved")

        if sufficient:
            return ResolutionDecision(
                action=ResolutionAction.AWAIT_CUSTOMER,
                reason="evidence_sufficient",
                evidence_sufficient=True,
                outcome=ResolutionOutcome.UNRESOLVED,
            )

        return self._retry_or_escalate(state, reason="insufficient_evidence")

    # -- internals ---------------------------------------------------------

    def _evidence_sufficient(self, state: AgentState) -> bool:
        return (
            state.error is None
            and bool(state.answer and state.answer.strip())
            and not state.abstained
            and not state.needs_clarification
        )

    def _retry_or_escalate(self, state: AgentState, *, reason: str) -> ResolutionDecision:
        if state.retry_count < self._config.max_retry_attempts:
            retry_agent = self._alternative_agent(state.selected_agent)
            if retry_agent is not None:
                return ResolutionDecision(
                    action=ResolutionAction.RETRY,
                    reason=reason,
                    evidence_sufficient=False,
                    retry_agent=retry_agent,
                )
        return ResolutionDecision(
            action=ResolutionAction.ESCALATE,
            reason=f"{reason}_exhausted" if state.retry_count else reason,
            evidence_sufficient=False,
            outcome=ResolutionOutcome.UNRESOLVED,
        )

    @staticmethod
    def _alternative_agent(agent: AgentName | None) -> AgentName | None:
        """Pick an alternative agent to retry with: knowledge lookup via the Policy agent.

        If the current agent already is (or cannot fall back to) a retryable one, there is no
        alternative and the caller escalates.
        """
        if agent in (None, AgentName.POLICY, AgentName.ESCALATION, AgentName.GENERAL):
            return None
        if agent in _RETRYABLE_AGENTS:
            return AgentName.POLICY
        return None
