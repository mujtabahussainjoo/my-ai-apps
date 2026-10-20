"""Optional external tracing export (FR-057, INT-006).

LangSmith (or an OTel-compatible endpoint) export is **disabled by default** and enabled only
through configuration. This module does not import any tracing SDK — it translates validated
settings into the environment variables that LangChain/LangSmith read at runtime, so the
dependency stays optional and a missing package never breaks the service.

Chain-of-thought, secrets, and PII must never be exported (FR-056): callers are expected to pass
only correlation ids/labels as trace metadata.
"""

from __future__ import annotations

import os

from ecommerce_support.core.config import Settings
from ecommerce_support.core.logging import get_logger

_logger = get_logger("ecommerce_support.tracing")


def tracing_enabled(settings: Settings) -> bool:
    """True when tracing is switched on *and* the required credentials are configured."""
    observability = settings.observability
    return bool(observability.tracing_enabled and observability.langsmith_api_key)


def configure_tracing(settings: Settings) -> bool:
    """Enable external tracing when configured; no-op (returns ``False``) otherwise.

    The default configuration has tracing disabled, so this is a safe no-op in tests and local
    development. When enabled it exports LangSmith environment variables and returns ``True``.
    """
    if not settings.observability.tracing_enabled:
        return False
    api_key = settings.observability.langsmith_api_key
    if not api_key:
        _logger.warning("tracing.enabled_without_key", tracing="langsmith")
        return False

    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.observability.langsmith_project)
    os.environ.setdefault("LANGSMITH_PROJECT", settings.observability.langsmith_project)
    _logger.info(
        "tracing.enabled",
        tracing="langsmith",
        project=settings.observability.langsmith_project,
    )
    return True


__all__ = ["configure_tracing", "tracing_enabled"]
