"""Guardrail package: prompt-injection, PII, validation, and authorization (FR-032, SEC-*).

Security lives in code, not prompts: untrusted content (customer messages, retrieved documents,
tool outputs) is delimited/screened before it can influence an answer, sensitive data is redacted
on the way out, and access rules are enforced as typed errors.
"""

from ecommerce_support.guardrails.authorization import (
    AuthorizationPolicy,
    require_authenticated,
    require_ownership,
    require_scope,
)
from ecommerce_support.guardrails.input_validation import screen_input
from ecommerce_support.guardrails.output_validation import screen_output
from ecommerce_support.guardrails.pii import detect_pii, redact_pii
from ecommerce_support.guardrails.prompt_injection import (
    assess_prompt_injection,
    is_prompt_injection,
)
from ecommerce_support.guardrails.redaction import redact_text, redact_value

__all__ = [
    "AuthorizationPolicy",
    "assess_prompt_injection",
    "detect_pii",
    "is_prompt_injection",
    "redact_pii",
    "redact_text",
    "redact_value",
    "require_authenticated",
    "require_ownership",
    "require_scope",
    "screen_input",
    "screen_output",
]
