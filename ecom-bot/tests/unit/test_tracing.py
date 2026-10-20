"""Tests for optional external tracing configuration (FR-057, INT-006)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from ecommerce_support.core.config import ObservabilityConfig, Settings
from ecommerce_support.core.tracing import configure_tracing, tracing_enabled

_ENV_VARS = (
    "LANGCHAIN_TRACING_V2",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_PROJECT",
    "LANGSMITH_PROJECT",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    saved = {name: os.environ.get(name) for name in _ENV_VARS}
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _settings(**observability: object) -> Settings:
    return Settings(
        _env_file=None,
        observability=ObservabilityConfig(**observability),  # type: ignore[arg-type]
    )


def test_tracing_disabled_by_default() -> None:
    settings = _settings()
    assert settings.observability.tracing_enabled is False
    assert tracing_enabled(settings) is False
    assert configure_tracing(settings) is False
    assert all(name not in os.environ for name in _ENV_VARS)


def test_tracing_enabled_requires_api_key() -> None:
    settings = _settings(tracing_enabled=True)
    assert tracing_enabled(settings) is False
    assert configure_tracing(settings) is False
    assert "LANGCHAIN_TRACING_V2" not in os.environ


def test_tracing_enabled_exports_environment() -> None:
    settings = _settings(
        tracing_enabled=True,
        langsmith_api_key="ls-test-key",
        langsmith_project="support-eval",
    )
    assert tracing_enabled(settings) is True
    assert configure_tracing(settings) is True
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "ls-test-key"
    assert os.environ["LANGSMITH_PROJECT"] == "support-eval"


def test_configure_tracing_does_not_override_existing_env() -> None:
    os.environ["LANGSMITH_PROJECT"] = "preexisting"
    settings = _settings(tracing_enabled=True, langsmith_api_key="ls-key")
    configure_tracing(settings)
    assert os.environ["LANGSMITH_PROJECT"] == "preexisting"
