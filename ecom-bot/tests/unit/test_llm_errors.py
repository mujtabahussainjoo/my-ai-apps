"""Tests for provider-agnostic LLM error normalization (TASK-014)."""

from __future__ import annotations

import anthropic
import httpx

from ecommerce_support.core.exceptions import (
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from ecommerce_support.llm.errors import normalize_error


class _WithStatus(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class _RateLimit(Exception):
    pass


def test_passes_through_existing_llm_error() -> None:
    original = LLMError("boom", retryable=False)
    assert normalize_error("p", original) is original


def test_auth_status_and_name() -> None:
    assert isinstance(normalize_error("p", _WithStatus("x", 401)), LLMAuthError)
    assert isinstance(normalize_error("p", _WithStatus("x", 403)), LLMAuthError)
    assert isinstance(normalize_error("p", AuthenticationErrorLike()), LLMAuthError)


def test_rate_limit() -> None:
    assert isinstance(normalize_error("p", _WithStatus("x", 429)), LLMRateLimitError)
    assert isinstance(normalize_error("p", RateLimitErrorLike()), LLMRateLimitError)
    assert isinstance(normalize_error("p", _RateLimit("slow")), LLMRateLimitError)


def test_timeout() -> None:
    assert isinstance(normalize_error("p", _WithStatus("x", 408)), LLMTimeoutError)
    assert isinstance(normalize_error("p", _WithStatus("x", 504)), LLMTimeoutError)
    assert isinstance(normalize_error("p", TimeoutError("t")), LLMTimeoutError)


def test_server_errors_retryable() -> None:
    error = normalize_error("p", _WithStatus("x", 503))
    assert isinstance(error, LLMError)
    assert error.retryable is True


def test_client_errors_not_retryable() -> None:
    error = normalize_error("p", _WithStatus("x", 400))
    assert isinstance(error, LLMError)
    assert error.retryable is False


def test_connection_retryable() -> None:
    error = normalize_error("p", ConnectionErrorLike())
    assert isinstance(error, LLMError)
    assert error.retryable is True


def test_unknown_defaults_retryable() -> None:
    error = normalize_error("p", RuntimeError("weird"))
    assert isinstance(error, LLMError)
    assert error.retryable is True


def test_details_include_provider_and_type() -> None:
    error = normalize_error("anthropic", _WithStatus("x", 500))
    assert error.details["provider"] == "anthropic"
    assert error.details["error_type"] == "_WithStatus"
    assert error.details["status_code"] == 500


def test_real_anthropic_errors() -> None:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp401 = httpx.Response(401, request=req)
    resp429 = httpx.Response(429, request=req)
    assert isinstance(
        normalize_error(
            "anthropic", anthropic.AuthenticationError("no", response=resp401, body=None)
        ),
        LLMAuthError,
    )
    assert isinstance(
        normalize_error("anthropic", anthropic.RateLimitError("slow", response=resp429, body=None)),
        LLMRateLimitError,
    )
    assert isinstance(
        normalize_error("anthropic", anthropic.APITimeoutError(request=req)), LLMTimeoutError
    )


def test_status_takes_precedence_over_class_name() -> None:
    # A RateLimitError carrying a 401 response is classified by status, not class name.
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp401 = httpx.Response(401, request=req)
    error = normalize_error("anthropic", anthropic.RateLimitError("x", response=resp401, body=None))
    assert isinstance(error, LLMAuthError)


class AuthenticationErrorLike(Exception):
    """Name-based match used to exercise class-name classification."""


class RateLimitErrorLike(Exception):
    """Name-based match used to exercise class-name classification."""


class ConnectionErrorLike(Exception):
    """Name-based match used to exercise class-name classification."""


def test_message_does_not_leak_provider_text() -> None:
    error = normalize_error("p", RuntimeError("secret-token-abc"))
    assert "secret-token-abc" not in error.message
    assert "secret-token-abc" not in str(error.to_dict())
    # The raw type is recorded, not the message body.
    assert error.details["error_type"] == "RuntimeError"


def test_ensure_capability_from_capabilities_module() -> None:
    # Smoke: the shared normalizer is independent of capabilities.
    assert normalize_error("p", RuntimeError("x")).code == "llm_error"
