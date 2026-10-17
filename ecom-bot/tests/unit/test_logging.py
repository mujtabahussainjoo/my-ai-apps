"""Tests for structured logging processors and configuration."""

from __future__ import annotations

from ecommerce_support.core.config import AppConfig, LogFormat, Settings
from ecommerce_support.core.logging import (
    _inject_trace_context,
    _redact_sensitive,
    configure_logging,
    get_logger,
    reset_logging,
)
from ecommerce_support.core.observability import request_context


def test_redact_sensitive_keys() -> None:
    event = {"message": "hello", "api_key": "secret", "Authorization": "Bearer x"}
    result = _redact_sensitive(None, "info", dict(event))
    assert result["api_key"] == "***redacted***"
    assert result["Authorization"] == "***redacted***"
    assert result["message"] == "hello"


def test_trace_context_injected() -> None:
    with request_context("req_test123", "conv_1"):
        result = _inject_trace_context(None, "info", {"event": "x"})
    assert result["request_id"] == "req_test123"
    assert result["conversation_id"] == "conv_1"


def test_configure_logging_structured_and_plain(capsys) -> None:
    settings = Settings(
        _env_file=None,
        app=AppConfig(log_format=LogFormat.structured, log_level="debug"),
    )
    configure_logging(settings, force=True)
    log = get_logger("test")
    log.info("structured_event", answer=42)
    captured = capsys.readouterr()
    assert "structured_event" in captured.err
    assert '"answer": 42' in captured.err

    plain = Settings(
        _env_file=None,
        app=AppConfig(log_format=LogFormat.plain, log_level="info"),
    )
    configure_logging(plain, force=True)
    get_logger("test").info("plain_event")
    assert "plain_event" in capsys.readouterr().err
    reset_logging()
