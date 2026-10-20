"""Unit tests for the deterministic/LLM intent router (TASK-027)."""

from __future__ import annotations

import pytest

from ecommerce_support.agents import Router, classify_message
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.schemas.enums import AgentName, Intent


@pytest.mark.parametrize(
    ("message", "intent", "agent"),
    [
        ("Where is my order ord-1?", Intent.ORDER, AgentName.ORDER),
        ("Track my package please", Intent.ORDER, AgentName.ORDER),
        ("Can I return this item?", Intent.ORDER, AgentName.ORDER),
        ("Do you have the hammer in stock?", Intent.PRODUCT, AgentName.PRODUCT),
        ("What is the price of the drill?", Intent.PRODUCT, AgentName.PRODUCT),
        ("What is your refund policy?", Intent.POLICY, AgentName.POLICY),
        ("How long does shipping take?", Intent.POLICY, AgentName.POLICY),
        ("Can you show my account?", Intent.ACCOUNT, AgentName.ACCOUNT),
        ("I want to talk to a human", Intent.ESCALATION, AgentName.ESCALATION),
        ("I want to leave feedback", Intent.FEEDBACK, AgentName.FEEDBACK),
        ("hello there", Intent.GENERAL, AgentName.GENERAL),
    ],
)
def test_deterministic_routing(message: str, intent: Intent, agent: AgentName) -> None:
    decision = classify_message(message)
    assert decision is not None
    assert decision.intent is intent
    assert decision.agent is agent


def test_empty_message_clarifies() -> None:
    decision = classify_message("   ")
    assert decision is not None
    assert decision.intent is Intent.CLARIFY


def test_unknown_message_has_no_deterministic_match() -> None:
    assert classify_message("zzz blorp") is None


@pytest.mark.parametrize("intent", list(Intent))
def test_intent_agent_mapping_is_total(intent: Intent) -> None:
    from ecommerce_support.agents.router import INTENT_AGENT

    assert intent in INTENT_AGENT


class TestLlmFallback:
    async def test_ambiguous_uses_llm_classifier(self) -> None:
        client = MockLLMClient(structured_outputs=[{"intent": "product"}])
        decision = await Router(client).route("I need help with that thing")
        assert decision.intent is Intent.PRODUCT
        assert decision.agent is AgentName.PRODUCT
        assert decision.reason == "llm_classifier"
        assert len(client.structured_requests) == 1

    async def test_falls_back_to_clarify_without_llm(self) -> None:
        decision = await Router().route("mumble mumble")
        assert decision.intent is Intent.CLARIFY
        assert decision.agent is AgentName.GENERAL
        assert decision.reason == "no_deterministic_match"

    async def test_deterministic_match_skips_llm(self) -> None:
        client = MockLLMClient(structured_outputs=[{"intent": "general"}])
        decision = await Router(client).route("Where is my order?")
        assert decision.intent is Intent.ORDER
        assert client.structured_requests == []

    async def test_llm_disabled_uses_clarify(self) -> None:
        client = MockLLMClient(structured_outputs=[{"intent": "order"}])
        decision = await Router(client, enable_llm=False).route("vague request")
        assert decision.intent is Intent.CLARIFY
        assert client.structured_requests == []


class TestRequiresAuth:
    def test_order_and_account_require_auth(self) -> None:
        assert classify_message("where is my order").requires_auth is True  # type: ignore[union-attr]
        assert classify_message("show my account").requires_auth is True  # type: ignore[union-attr]

    def test_product_and_policy_are_public(self) -> None:
        assert classify_message("do you have hammers").requires_auth is False  # type: ignore[union-attr]
        assert classify_message("what is your warranty").requires_auth is False  # type: ignore[union-attr]
