"""Tests for the exception hierarchy."""

from __future__ import annotations

from ecommerce_support.core.exceptions import (
    AppError,
    AuthorizationError,
    LLMAuthError,
    LLMCapabilityError,
    TicketCreationError,
    is_retryable,
)


def test_app_error_defaults() -> None:
    err = AppError()
    payload = err.to_dict()
    assert payload["code"] == "internal_error"
    assert payload["retryable"] is False
    assert err.http_status == 500


def test_subclass_codes_and_status() -> None:
    assert AuthorizationError().http_status == 403
    assert AuthorizationError().code == "forbidden"
    assert TicketCreationError("nope").http_status == 502


def test_retryability_flags() -> None:
    assert is_retryable(TicketCreationError("x")) is True
    assert is_retryable(LLMCapabilityError("unsupported")) is False
    assert is_retryable(LLMAuthError("bad key")) is False
    assert is_retryable(ValueError("plain")) is False


def test_details_are_carried() -> None:
    err = AppError("bad", code="custom", details={"field": "email"})
    assert err.to_dict()["details"] == {"field": "email"}
    assert err.code == "custom"
