"""Unit tests for the Resolution Agent decision logic (FR-024/FR-048, TASK-028)."""

from __future__ import annotations

from ecommerce_support.agents.resolution import ResolutionAgent
from ecommerce_support.core.config import AgentsConfig
from ecommerce_support.schemas.agents import AgentState
from ecommerce_support.schemas.enums import AgentName, ResolutionAction, ResolutionOutcome


def _state(**overrides: object) -> AgentState:
    data: dict[str, object] = {"conversation_id": "conv-1", "user_id": "cust-1"}
    data.update(overrides)
    return AgentState(**data)


def _agent(**config_kwargs: object) -> ResolutionAgent:
    return ResolutionAgent(AgentsConfig(**config_kwargs))


class TestSufficientEvidence:
    def test_usable_answer_awaits_customer(self) -> None:
        decision = _agent().assess(
            _state(
                selected_agent=AgentName.ORDER,
                intent=None,
                answer="Your order ord-1 is out for delivery.",
            )
        )
        assert decision.action is ResolutionAction.AWAIT_CUSTOMER
        assert decision.evidence_sufficient is True
        assert decision.outcome is ResolutionOutcome.UNRESOLVED

    def test_abstained_answer_is_not_sufficient(self) -> None:
        decision = _agent(max_retry_attempts=0).assess(
            _state(selected_agent=AgentName.POLICY, answer="I don't know.", abstained=True)
        )
        assert decision.action is ResolutionAction.ESCALATE
        assert decision.evidence_sufficient is False

    def test_error_is_not_sufficient(self) -> None:
        decision = _agent(max_retry_attempts=0).assess(
            _state(selected_agent=AgentName.ORDER, answer="try again", error="worker_failed")
        )
        assert decision.action is ResolutionAction.ESCALATE


class TestCustomerSignal:
    def test_confirmation_resolves(self) -> None:
        decision = _agent().assess(_state(answer="ok"), resolved=True)
        assert decision.action is ResolutionAction.RESOLVED
        assert decision.outcome is ResolutionOutcome.RESOLVED
        assert decision.reason == "customer_confirmed"

    def test_unresolved_retries_when_attempts_remain(self) -> None:
        decision = _agent(max_retry_attempts=1).assess(
            _state(selected_agent=AgentName.PRODUCT, answer="Here it is."), resolved=False
        )
        assert decision.action is ResolutionAction.RETRY
        assert decision.retry_agent is AgentName.POLICY
        assert decision.reason == "customer_reported_unresolved"

    def test_unresolved_escalates_when_exhausted(self) -> None:
        decision = _agent(max_retry_attempts=1).assess(
            _state(selected_agent=AgentName.PRODUCT, answer="Here it is.", retry_count=1),
            resolved=False,
        )
        assert decision.action is ResolutionAction.ESCALATE
        assert decision.outcome is ResolutionOutcome.UNRESOLVED


class TestAlternativeAgent:
    def test_policy_has_no_alternative(self) -> None:
        decision = _agent(max_retry_attempts=2).assess(
            _state(selected_agent=AgentName.POLICY, answer="", abstained=True)
        )
        assert decision.action is ResolutionAction.ESCALATE

    def test_escalation_agent_has_no_alternative(self) -> None:
        decision = _agent(max_retry_attempts=2).assess(
            _state(selected_agent=AgentName.ESCALATION, error="worker_failed")
        )
        assert decision.action is ResolutionAction.ESCALATE

    def test_account_retries_via_policy(self) -> None:
        decision = _agent(max_retry_attempts=2).assess(
            _state(selected_agent=AgentName.ACCOUNT, error="worker_failed")
        )
        assert decision.action is ResolutionAction.RETRY
        assert decision.retry_agent is AgentName.POLICY
