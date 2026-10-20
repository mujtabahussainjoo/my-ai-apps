"""Intent router: deterministic fast-path with an LLM fallback (FR-015-FR-018).

Routing is deterministic first (keyword patterns for order/tracking/return/product/account/policy/
feedback/escalation/greeting) so behavior is stable, testable, and offline. Only genuinely
ambiguous messages fall back to the LLM classifier; if that is unavailable or inconclusive the
router returns a ``clarify`` decision instead of guessing.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ecommerce_support.llm.base import LLMClient
from ecommerce_support.llm.capabilities import LLMCapability
from ecommerce_support.llm.types import ChatMessage, CompletionRequest, Role
from ecommerce_support.schemas.agents import RoutingDecision
from ecommerce_support.schemas.enums import AgentName, Intent

INTENT_AGENT: dict[Intent, AgentName] = {
    Intent.ORDER: AgentName.ORDER,
    Intent.PRODUCT: AgentName.PRODUCT,
    Intent.POLICY: AgentName.POLICY,
    Intent.ACCOUNT: AgentName.ACCOUNT,
    Intent.FEEDBACK: AgentName.FEEDBACK,
    Intent.ESCALATION: AgentName.ESCALATION,
    Intent.GENERAL: AgentName.GENERAL,
    Intent.CLARIFY: AgentName.GENERAL,
}

INTENT_REQUIRES_AUTH: dict[Intent, bool] = {
    Intent.ORDER: True,
    Intent.ACCOUNT: True,
    Intent.FEEDBACK: True,
    Intent.ESCALATION: True,
    Intent.PRODUCT: False,
    Intent.POLICY: False,
    Intent.GENERAL: False,
    Intent.CLARIFY: False,
}

_CLASSIFIER_SYSTEM = (
    "You classify customer-support messages for an e-commerce store into exactly one intent: "
    "order, product, policy, account, feedback, escalation, general, or clarify. Use 'clarify' "
    "when the message is too vague to act on. Reply only with the intent label."
)


class _IntentChoice(BaseModel):
    """Structured output requested from the LLM fallback classifier."""

    intent: Intent = Field(description="One of the supported intents")


def _rules() -> list[tuple[Intent, tuple[str, ...]]]:
    """Ordered deterministic rules; earlier intents win on overlap (most specific first)."""
    return [
        (
            Intent.GENERAL,
            (r"\b(hi|hello|hey|good (morning|afternoon|evening))\b", r"\b(thanks|thank you)\b"),
        ),
        (
            Intent.ESCALATION,
            (
                r"\b(human|representative|escalate|supervisor|manager)\b",
                r"\b(talk|speak) to (someone|a person|an agent)\b",
            ),
        ),
        (
            Intent.FEEDBACK,
            (r"\b(feedback|review|rating|complaint|suggestion)\b",),
        ),
        (
            Intent.ACCOUNT,
            (
                r"\bmy account\b",
                r"\b(profile|account details|my details)\b",
                r"\b(email|name) on file\b",
                r"\b(signed|logged) in\b",
            ),
        ),
        (
            Intent.POLICY,
            (
                r"\bpolic(y|ies)\b",
                r"\b(warranty|guarantee|terms of service|faq)\b",
                r"\bhow long (does|do|is)\b",
                r"\ballowed to\b",
            ),
        ),
        (
            Intent.ORDER,
            (
                r"\border(s)?\b",
                r"\b(track|tracking)\b",
                r"\bshipment\b",
                r"\b(deliver|delivery|delivered)\b",
                r"\bpackage\b",
                r"\b(refund|return|returns)\b",
                r"\bcancel\b",
            ),
        ),
        (
            Intent.PRODUCT,
            (
                r"\bproduct(s)?\b",
                r"\b(price|pricing|cost)\b",
                r"\b(stock|in stock|out of stock|availability|available)\b",
                r"\bsku\b",
                r"\b(catalog|catalogue)\b",
                r"\bdo you (sell|have|carry)\b",
            ),
        ),
    ]


_COMPILED: list[tuple[Intent, tuple[re.Pattern[str], ...]]] = [
    (intent, tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns))
    for intent, patterns in _rules()
]


def classify_message(message: str) -> RoutingDecision | None:
    """Deterministic classification; ``None`` when no rule matches (caller may use the LLM)."""
    text = message.strip()
    if not text:
        return RoutingDecision(
            intent=Intent.CLARIFY,
            agent=AgentName.GENERAL,
            requires_auth=False,
            confidence=1.0,
            reason="empty_message",
        )
    for intent, patterns in _COMPILED:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return RoutingDecision(
                    intent=intent,
                    agent=INTENT_AGENT[intent],
                    requires_auth=INTENT_REQUIRES_AUTH[intent],
                    confidence=1.0,
                    reason=f"pattern:{pattern.pattern}",
                )
    return None


def decision_for_intent(
    intent: Intent, *, confidence: float | None = None, reason: str = ""
) -> RoutingDecision:
    """Build a consistent decision (agent + auth flag) for an intent."""
    return RoutingDecision(
        intent=intent,
        agent=INTENT_AGENT[intent],
        requires_auth=INTENT_REQUIRES_AUTH[intent],
        confidence=confidence,
        reason=reason,
    )


class Router:
    """Deterministic fast-path router with an optional LLM fallback."""

    def __init__(self, client: LLMClient | None = None, *, enable_llm: bool = True) -> None:
        self._client = client
        self._enable_llm = enable_llm and client is not None

    @property
    def llm_enabled(self) -> bool:
        return self._enable_llm and self._client is not None

    async def route(self, message: str) -> RoutingDecision:
        """Route ``message`` to an intent/agent; never raises for ambiguous input."""
        decision = classify_message(message)
        if decision is not None:
            return decision

        if self.llm_enabled:
            llm_decision = await self._classify_with_llm(message)
            if llm_decision is not None:
                return llm_decision

        return decision_for_intent(Intent.CLARIFY, confidence=0.0, reason="no_deterministic_match")

    async def _classify_with_llm(self, message: str) -> RoutingDecision | None:
        client = self._client
        if client is None:  # pragma: no cover - guarded by llm_enabled
            return None
        if not client.supports(LLMCapability.structured):
            return None
        try:
            choice = await client.structured(
                CompletionRequest(
                    messages=[ChatMessage(role=Role.user, content=message)],
                    system=_CLASSIFIER_SYSTEM,
                    temperature=0.0,
                    metadata={"purpose": "intent_router"},
                ),
                _IntentChoice,
            )
        except Exception:  # classification must never break a chat turn
            return None
        return decision_for_intent(choice.intent, confidence=0.5, reason="llm_classifier")
