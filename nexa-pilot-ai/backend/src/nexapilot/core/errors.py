"""Normalized error taxonomy shared by providers, tools and the API layer.

Every layer raises a :class:`NexaPilotError` subclass so the API can translate a
failure into a stable, non-leaky payload (never raw provider payloads that could
contain credentials).
"""

from __future__ import annotations

from typing import Any


class NexaPilotError(Exception):
    """Base class for every error raised by the backend."""

    code: str = "internal_error"
    http_status: int = 500
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        setup_hint: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.setup_hint = setup_hint
        if setup_hint:
            self.details.setdefault("setup_hint", setup_hint)

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
            "setup_hint": self.setup_hint,
        }


class ConfigurationError(NexaPilotError):
    code = "configuration_error"
    http_status = 400


class ValidationError(NexaPilotError):
    code = "validation_error"
    http_status = 422


class RunCancelledError(NexaPilotError):
    """Raised when the user cancels an in-flight run."""

    code = "cancelled"
    http_status = 409


class NotFoundError(NexaPilotError):
    code = "not_found"
    http_status = 404


class PermissionDeniedError(NexaPilotError):
    code = "permission_denied"
    http_status = 403


class ApprovalRequiredError(NexaPilotError):
    code = "approval_required"
    http_status = 409


class ProviderError(NexaPilotError):
    code = "provider_error"
    http_status = 502


class ProviderAuthError(ProviderError):
    code = "provider_auth_error"
    http_status = 401


class ProviderRateLimitError(ProviderError):
    code = "provider_rate_limit"
    http_status = 429
    retryable = True


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    http_status = 504
    retryable = True


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    http_status = 503
    retryable = True


class CapabilityNotSupportedError(ProviderError):
    code = "capability_not_supported"
    http_status = 400


class ToolExecutionError(NexaPilotError):
    code = "tool_execution_error"
    http_status = 500


class ToolTimeoutError(ToolExecutionError):
    code = "tool_timeout"
    http_status = 504
    retryable = True


class SandboxViolationError(PermissionDeniedError):
    code = "sandbox_violation"
    http_status = 403


class IntegrationError(NexaPilotError):
    code = "integration_error"
    http_status = 502


class ExternalServiceNotConfiguredError(NexaPilotError):
    """Raised when a workflow needs a provider the user has not configured."""

    code = "not_configured"
    http_status = 409

    def __init__(self, message: str, *, setup_hint: str = "") -> None:
        super().__init__(message, setup_hint=setup_hint)
