"""Input validation guardrail: size limits + prompt-injection screening (SEC-009, FR-032).

Framework-free and deterministic so it runs on every turn without an LLM:

- oversized messages are blocked (a denial-of-service control, SEC-009);
- prompt-injection attempts are blocked unless configured to merely flag (FR-032).

Returns a :class:`GuardrailDecision`; the caller (``ChatService``) turns a ``block`` into a
refusal and logs a security event.
"""

from __future__ import annotations

from ecommerce_support.core.config import GuardrailAction
from ecommerce_support.guardrails.prompt_injection import assess_prompt_injection
from ecommerce_support.schemas.guardrails import GuardrailDecision, allow, block

INPUT_TOO_LONG = "input_too_long"
PROMPT_INJECTION = "prompt_injection"


def screen_input(
    message: str,
    *,
    max_chars: int,
    injection_threshold: float = 0.7,
    enabled: bool = True,
    injection_action: GuardrailAction = GuardrailAction.block,
) -> GuardrailDecision:
    """Screen an incoming customer message before it reaches the graph."""
    if not enabled:
        return allow()
    if len(message) > max_chars:
        return block(INPUT_TOO_LONG, "That message is too long.", matches=["input_length"])
    if injection_action is not GuardrailAction.block:
        return allow()
    assessment = assess_prompt_injection(message, threshold=injection_threshold)
    if assessment.flagged:
        return block(
            PROMPT_INJECTION, "I can't help with that request.", matches=assessment.matches
        )
    return allow()


__all__ = ["INPUT_TOO_LONG", "PROMPT_INJECTION", "screen_input"]
