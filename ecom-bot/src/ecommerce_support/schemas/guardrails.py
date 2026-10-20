"""Guardrail contracts: prompt-injection, PII, and validation decisions (FR-032, SEC-003/004/005).

These are framework-free Pydantic v2 contracts. Guardrail functions return a
:class:`GuardrailDecision` so callers get a uniform, loggable outcome (allow / redact / block)
instead of ad-hoc booleans, and every decision carries a stable machine-readable ``code``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ecommerce_support.schemas.common import Schema


class InjectionAssessment(Schema):
    """Result of scanning a piece of text for prompt-injection attempts."""

    score: float = Field(ge=0.0, le=1.0)
    flagged: bool
    matches: list[str] = Field(default_factory=list)


class PiiAssessment(Schema):
    """Categories of PII/secret detected in a piece of text (never the values themselves)."""

    flagged: bool
    kinds: list[str] = Field(default_factory=list)


class GuardrailOutcome(StrEnum):
    """Disposition of a piece of text after screening."""

    allow = "allow"
    redact = "redact"
    block = "block"


class GuardrailDecision(Schema):
    """Uniform result of screening input or output text (SEC-003/004/005).

    ``text`` carries the sanitized value for a ``redact`` outcome (callers should use it in place
    of the original); it is ``None`` for ``allow``/``block``.
    """

    outcome: GuardrailOutcome
    code: str = ""
    reason: str = ""
    matches: list[str] = Field(default_factory=list)
    text: str | None = None

    @property
    def allowed(self) -> bool:
        """True when the text may be used unchanged (allow or redact)."""
        return self.outcome is not GuardrailOutcome.block

    @property
    def blocked(self) -> bool:
        """True when the text must not proceed."""
        return self.outcome is GuardrailOutcome.block

    @property
    def redacted(self) -> bool:
        """True when the text was modified by redaction."""
        return self.outcome is GuardrailOutcome.redact


def allow() -> GuardrailDecision:
    """Build an ``allow`` decision."""
    return GuardrailDecision(outcome=GuardrailOutcome.allow)


def block(code: str, reason: str, *, matches: list[str] | None = None) -> GuardrailDecision:
    """Build a ``block`` decision with a machine-readable ``code``."""
    return GuardrailDecision(
        outcome=GuardrailOutcome.block, code=code, reason=reason, matches=matches or []
    )


def redact(
    text: str, code: str, reason: str, *, matches: list[str] | None = None
) -> GuardrailDecision:
    """Build a ``redact`` decision carrying the sanitized ``text``."""
    return GuardrailDecision(
        outcome=GuardrailOutcome.redact,
        code=code,
        reason=reason,
        matches=matches or [],
        text=text,
    )


__all__ = [
    "GuardrailDecision",
    "GuardrailOutcome",
    "InjectionAssessment",
    "PiiAssessment",
    "allow",
    "block",
    "redact",
]
