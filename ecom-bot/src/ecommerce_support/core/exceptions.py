"""Typed exception hierarchy.

Every error raised by application code is a subclass of :class:`AppError`. The API layer
maps these to HTTP responses; business/worker code raises them without knowing about HTTP.
Error messages in ``message`` are always safe to show a customer (no secrets, no internals).
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error. Safe to surface to callers."""

    code: str = "internal_error"
    http_status: int = 500
    retryable: bool = False

    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or {}
        if retryable is not None:
            self.retryable = retryable
        self.headers = headers or {}

    def to_dict(self) -> dict[str, Any]:
        """Serializable, non-sensitive representation for API responses and logs."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
        }

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class ConfigurationError(AppError):
    code = "configuration_error"
    http_status = 500


class ValidationError(AppError):
    code = "validation_error"
    http_status = 422


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404


class AuthenticationError(AppError):
    code = "authentication_error"
    http_status = 401


class AuthorizationError(AppError):
    """Raised when a caller is authenticated but not permitted (e.g. cross-customer access)."""

    code = "forbidden"
    http_status = 403


class RateLimitError(AppError):
    code = "rate_limited"
    http_status = 429


class GuardrailViolation(AppError):
    """Input or output rejected by the guardrail layer."""

    code = "guardrail_violation"
    http_status = 400


class ConflictError(AppError):
    code = "conflict"
    http_status = 409


class InvalidStateTransition(AppError):
    code = "invalid_state_transition"
    http_status = 409


class ExternalServiceError(AppError):
    """A dependency (HTTP API, DB beyond connectivity, etc.) failed."""

    code = "external_service_error"
    http_status = 502
    retryable = True


class IngestionError(AppError):
    code = "ingestion_error"
    http_status = 422


class UnsupportedDocumentTypeError(IngestionError):
    """The uploaded document's type is not one of the supported loaders (FR-035)."""

    code = "unsupported_document_type"


class DocumentTooLargeError(IngestionError):
    """The uploaded document exceeds the configured maximum size (FR-035)."""

    code = "document_too_large"


# --- LLM layer -------------------------------------------------------------


class LLMError(ExternalServiceError):
    code = "llm_error"


class LLMCapabilityError(LLMError):
    """The selected provider/model does not support a requested capability.

    Raised loudly instead of silently degrading (see AGENTS.md / requirements).
    """

    code = "llm_capability_error"
    retryable = False


class LLMTimeoutError(LLMError):
    code = "llm_timeout"


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"


class LLMAuthError(LLMError):
    code = "llm_auth_error"
    retryable = False


# --- Embeddings (RAG) ------------------------------------------------------


class EmbeddingError(ExternalServiceError):
    """An embedding provider failed (network, auth, malformed response)."""

    code = "embedding_error"


class EmbeddingDimensionError(EmbeddingError):
    """An embedding vector's length does not match the fixed schema dimension (FR-036).

    Raised loudly instead of silently degrading or truncating vectors.
    """

    code = "embedding_dimension_error"
    retryable = False


# --- Integrations ----------------------------------------------------------


class IntegrationError(ExternalServiceError):
    code = "integration_error"


class CommerceError(IntegrationError):
    code = "commerce_error"


class TicketingError(IntegrationError):
    code = "ticketing_error"


class TicketCreationError(TicketingError):
    """External ticketing service did not confirm ticket creation."""

    code = "ticket_creation_failed"


def is_retryable(error: BaseException) -> bool:
    """True when the error class is marked retryable by policy."""
    return isinstance(error, AppError) and error.retryable
