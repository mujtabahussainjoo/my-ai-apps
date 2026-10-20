"""Unit tests for PII detection and redaction (TASK-039, SEC-005/FR-051)."""

from __future__ import annotations

from ecommerce_support.guardrails.pii import detect_pii, redact_pii
from ecommerce_support.guardrails.redaction import redact_value


def test_clean_text_has_no_pii() -> None:
    assessment = detect_pii("Where is my order 12345?")
    assert assessment.flagged is False
    assert assessment.kinds == []


def test_detects_email_card_ssn_and_secret() -> None:
    assessment = detect_pii(
        "mail ada@example.com card 4111 1111 1111 1111 ssn 123-45-6789 token=abc123"
    )
    assert assessment.flagged is True
    for kind in ("email", "card", "ssn", "secret"):
        assert kind in assessment.kinds


def test_detection_never_returns_values() -> None:
    assessment = detect_pii("ada@example.com")
    assert "ada@example.com" not in " ".join(assessment.kinds)


def test_redact_pii_masks_everything_sensitive() -> None:
    text = "email ada@example.com, card 4111 1111 1111 1111, ip 10.0.0.1, key sk-live-abcdef"
    redacted = redact_pii(text)
    for secret in ("ada@example.com", "4111", "10.0.0.1", "sk-live-abcdef"):
        assert secret not in redacted
    assert "[redacted]" in redacted


def test_redact_value_recurses_structures() -> None:
    payload = {"note": "call 5551234567", "items": ["a@b.com"], "count": 3}
    redacted = redact_value(payload)
    assert redacted["note"] == "call [redacted]"
    assert redacted["items"] == ["[redacted]"]
    assert redacted["count"] == 3
