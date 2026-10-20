"""Output validation guardrail: redact secrets/PII from answers (SEC-004/SEC-005, FR-051).

Safe by default: rather than block an answer, strip credentials, payment numbers, and unnecessary
PII before the text is persisted or streamed. Callers use ``decision.text`` when ``redacted``.
"""

from __future__ import annotations

from ecommerce_support.guardrails.pii import detect_pii, redact_pii
from ecommerce_support.schemas.guardrails import GuardrailDecision, allow, redact

OUTPUT_REDACTED = "output_redacted"


def screen_output(text: str, *, enabled: bool = True) -> GuardrailDecision:
    """Redact secrets/PII from ``text`` before it is persisted or sent (SEC-004/005).

    Returns ``REDACT`` (carrying the sanitized text) when anything was masked, else ``ALLOW``.
    """
    if not enabled:
        return allow()
    sanitized = redact_pii(text)
    if sanitized == text:
        return allow()
    return redact(
        sanitized,
        "output_redacted",
        "Sensitive data was removed.",
        matches=detect_pii(text).kinds,
    )


__all__ = ["screen_output"]
