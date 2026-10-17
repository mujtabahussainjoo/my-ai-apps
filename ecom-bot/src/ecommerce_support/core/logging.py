"""Structured logging configuration built on structlog.

Design goals:
- JSON logs in production-style environments (``log_format=structured``), human-readable
  console output otherwise.
- Correlation ids from :mod:`ecommerce_support.core.observability` are injected into every
  event automatically via ``contextvars``.
- Secrets/chain-of-thought/PII must never be logged by callers; this module only provides
  the machinery and a helper to redact known-sensitive keys defensively.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from ecommerce_support.core.config import LogFormat, Settings
from ecommerce_support.core.observability import TraceContext

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "jwt",
        "jwt_secret",
        "access_token",
        "refresh_token",
        "card_number",
        "cvv",
        "authorization_header",
    }
)

_configured = False


def _inject_trace_context(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    ctx = TraceContext.current()
    if ctx.request_id:
        event_dict.setdefault("request_id", ctx.request_id)
    if ctx.conversation_id:
        event_dict.setdefault("conversation_id", ctx.conversation_id)
    return event_dict


def _redact_sensitive(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "***redacted***"
    return event_dict


def configure_logging(settings: Settings, *, force: bool = False) -> None:
    """Configure stdlib + structlog for the whole process (idempotent)."""
    global _configured
    if _configured and not force:
        return

    level = getattr(logging, settings.app.log_level.value.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_trace_context,
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.app.log_format is LogFormat.structured:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    for noisy in ("uvicorn.access", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger; call :func:`configure_logging` first."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def reset_logging() -> None:
    """Reset structlog config (tests only)."""
    global _configured
    structlog.reset_defaults()
    _configured = False
