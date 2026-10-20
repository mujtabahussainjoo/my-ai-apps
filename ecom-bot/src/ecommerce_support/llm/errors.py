"""Provider-agnostic error normalization for the LLM layer.

Provider SDKs raise their own exception types. At the LLM boundary we translate them to the
app's typed :mod:`ecommerce_support.core.exceptions` hierarchy so callers never depend on a
provider SDK and messages stay safe (no secrets, no raw provider text). Classification is by
exception class name and HTTP/status hints, which avoids importing every SDK here.

Retry policy (which classes are retryable) is recorded on the normalized error; the retry
engine itself lives in TASK-015.
"""

from __future__ import annotations

from ecommerce_support.core.exceptions import (
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)

_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_AUTH_STATUS = frozenset({401, 403})
_RATE_LIMIT_STATUS = frozenset({429})
_TIMEOUT_STATUS = frozenset({408, 504})


def _status_code(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def normalize_error(provider: str, error: Exception) -> LLMError:
    """Translate a provider exception into a typed, retry-classified :class:`LLMError`."""
    if isinstance(error, LLMError):
        return error

    name = type(error).__name__.lower()
    status = _status_code(error)
    details: dict[str, object] = {"provider": provider, "error_type": type(error).__name__}
    if status is not None:
        details["status_code"] = status

    if status in _AUTH_STATUS or "authentication" in name or "permissiondenied" in name:
        return LLMAuthError("LLM provider rejected the credentials.", details=details)
    if status in _RATE_LIMIT_STATUS or "ratelimit" in name or "resourceexhausted" in name:
        return LLMRateLimitError("LLM provider rate limit exceeded.", details=details)
    if status in _TIMEOUT_STATUS or "timeout" in name or "deadline" in name:
        return LLMTimeoutError("LLM provider request timed out.", details=details)
    if "connection" in name or "unavailable" in name:
        return LLMError("LLM provider is unreachable.", details=details, retryable=True)
    if status is not None and status >= 500:
        return LLMError("LLM provider server error.", details=details, retryable=True)
    if status is not None and 400 <= status < 500:
        return LLMError("LLM provider rejected the request.", details=details, retryable=False)
    # Unknown/transient-looking failure: allow retry by default.
    return LLMError("LLM provider call failed.", details=details, retryable=True)
