"""PII/secret redaction for outbound text and payloads (SEC-005, FR-051).

Security is code, not prompts: any text leaving the system toward an external ticketing service or
an operational log is scrubbed defensively. Redaction is intentionally aggressive — a false
positive is preferable to leaking a credential, payment number, or unnecessary PII. Structured
(non-string) fields are untouched except for recursive traversal.

``PII_PATTERNS`` is the single source of truth for what counts as PII; both redaction and
:mod:`ecommerce_support.guardrails.pii` detection are built from it so they never diverge.
"""

from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# 13-19 digit groups allowing spaces/dashes (payment cards).
_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
# US Social Security number (also catches similar national-id shapes).
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# IPv4 address.
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Any long digit run (phone/account/ids) not already caught by the card matcher.
_LONG_DIGITS_RE = re.compile(r"\b\d{7,}\b")

PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", _EMAIL_RE),
    ("card", _CARD_RE),
    ("ssn", _SSN_RE),
    ("ip_address", _IPV4_RE),
    ("phone", _LONG_DIGITS_RE),
)

_SECRET_RE = re.compile(
    r"(?i)\b(?:bearer\s+[\w.\-]+|sk-[A-Za-z0-9\-]{6,}|"
    r"(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+)"
)

# Public alias so PII detection can report credentials without re-declaring the pattern.
SECRET_PATTERN = _SECRET_RE

_REDACTED = "[redacted]"


def redact_text(text: str) -> str:
    """Return ``text`` with emails, card/id numbers, IPs, and inline secrets masked."""
    redacted = text
    for _kind, pattern in PII_PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return _SECRET_RE.sub(_REDACTED, redacted)


def redact_value(value: Any) -> Any:
    """Recursively redact strings inside dicts/lists/tuples, leaving other types intact."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value


__all__ = ["PII_PATTERNS", "SECRET_PATTERN", "redact_text", "redact_value"]
