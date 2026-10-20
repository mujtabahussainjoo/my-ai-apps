"""PII detection and minimization (SEC-005, FR-051).

Detection shares :data:`ecommerce_support.guardrails.redaction.PII_PATTERNS` with redaction so the
two never diverge. ``detect_pii`` reports only the *kinds* of PII found (never the values), which
makes it safe to log as a security/telemetry signal.
"""

from __future__ import annotations

from ecommerce_support.guardrails.redaction import PII_PATTERNS, SECRET_PATTERN, redact_text
from ecommerce_support.schemas.guardrails import PiiAssessment

_SECRET_HINT = "secret"


def detect_pii(text: str) -> PiiAssessment:
    """Return the kinds of PII/credentials present in ``text`` (values are never returned)."""
    probe = text or ""
    kinds = [kind for kind, pattern in PII_PATTERNS if pattern.search(probe)]
    if SECRET_PATTERN.search(probe):
        kinds.append(_SECRET_HINT)
    return PiiAssessment(flagged=bool(kinds), kinds=kinds)


def redact_pii(text: str) -> str:
    """Return ``text`` with all detected PII/credentials masked (delegates to ``redact_text``)."""
    return redact_text(text)


__all__ = ["detect_pii", "redact_pii"]
