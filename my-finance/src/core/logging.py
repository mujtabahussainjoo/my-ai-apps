"""Logging setup.

Every log record passes through :func:`src.core.security.redact`, so secrets
cannot reach stdout, the log aggregator, or a third-party observability vendor
even if a caller passes them in by mistake.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from src.core.config import Settings, get_settings
from src.core.security import redact

_CONFIGURED = False


def configure_logging(settings: Settings | None = None) -> None:
    """Idempotently configure structlog + stdlib logging with redaction."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = settings or get_settings()

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)
    logging.getLogger().setLevel(level)
    # httpx logs full request URLs, which can embed API keys as query params.
    logging.getLogger("httpx").setLevel(max(level, logging.WARNING))
    logging.getLogger("httpcore").setLevel(max(level, logging.WARNING))

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        _RedactProcessor(),
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


class _RedactProcessor:
    """structlog processor that redacts secrets from the event dict."""

    def __call__(self, logger: Any, name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        return redact(event_dict)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)


def log_risk_event(
    logger: Any,
    *,
    rule: str,
    symbol: str,
    message: str,
    severity: str = "warning",
    **extra: Any,
) -> None:
    """Emit a risk event in a consistent, greppable shape."""
    logger.log(
        getattr(logging, severity.upper(), logging.WARNING),
        "risk_event",
        rule=rule,
        symbol=symbol,
        reason=message,
        **extra,
    )
