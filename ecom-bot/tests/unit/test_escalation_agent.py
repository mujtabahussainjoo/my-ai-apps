"""Unit tests for the EscalationAgent payload builder (FR-025)."""

from __future__ import annotations

from ecommerce_support.agents.escalation import EscalationAgent
from ecommerce_support.schemas import AgentState, SourceCitation
from ecommerce_support.schemas.enums import Priority


def _state(**overrides: object) -> AgentState:
    data: dict[str, object] = {"conversation_id": "conv-1", "message": "My order never arrived."}
    data.update(overrides)
    return AgentState(**data)


def test_summary_uses_first_non_empty_line() -> None:
    agent = EscalationAgent()
    assert agent.summarize(_state(message="\n  Refund missing  \nmore")) == "Refund missing"


def test_summary_falls_back_when_blank() -> None:
    agent = EscalationAgent()
    assert agent.summarize(_state(message="   \n  ")) == "Customer requested human support."


def test_summary_is_length_bounded() -> None:
    agent = EscalationAgent(max_summary_chars=10)
    assert len(agent.summarize(_state(message="a" * 50))) == 10


def test_build_request_carries_context() -> None:
    agent = EscalationAgent()
    citation = SourceCitation(
        document_id="doc-1", chunk_id="chunk-1", document_title="Returns", score=0.9
    )
    request = agent.build_request(
        _state(
            message="Return window?",
            error="max_routing_hops_exceeded",
            attempts=["order", "policy"],
            evidence=[citation],
        )
    )
    assert request.conversation_id == "conv-1"
    assert request.priority is Priority.HIGH  # error present
    assert request.steps_attempted == ["order", "policy"]
    assert request.sources == [citation]
    assert request.actual_behavior == "max_routing_hops_exceeded"
    assert "Unresolved reason" in request.description


def test_build_request_defaults_to_medium_priority() -> None:
    agent = EscalationAgent()
    assert agent.build_request(_state()).priority is Priority.MEDIUM
