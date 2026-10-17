"""Tests for configuration loading, precedence, and validation."""

from __future__ import annotations

from pathlib import Path

import pydantic
import pytest

from ecommerce_support.core.config import (
    AppConfig,
    AppEnv,
    AuthConfig,
    LLMConfig,
    RagConfig,
    Settings,
    get_settings,
    reload_settings,
)


def test_defaults_load_from_yaml() -> None:
    settings = Settings(_env_file=None)
    assert settings.app.env is AppEnv.development
    assert settings.app.service_port == 8000
    assert settings.rag.top_k == 5
    assert settings.database.url.endswith(":5434/ecombot")
    assert settings.integrations.ticketing_provider.value == "mock"


def test_env_nested_override_wins_over_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP__SERVICE_PORT", "9999")
    monkeypatch.setenv("APP__LOG_LEVEL", "debug")
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://u:p@db:5432/x")
    settings = Settings(_env_file=None)
    assert settings.app.service_port == 9999
    assert settings.app.log_level.value == "debug"
    assert settings.database.url == "postgresql+asyncpg://u:p@db:5432/x"


def test_yaml_files_merge_and_env_overrides_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "rag.yaml").write_text("rag:\n  top_k: 9\n", encoding="utf-8")
    (tmp_path / "app.yaml").write_text("app:\n  service_port: 7000\n", encoding="utf-8")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    settings = Settings(_env_file=None)
    assert settings.rag.top_k == 9
    assert settings.app.service_port == 7000

    monkeypatch.setenv("RAG__TOP_K", "3")
    overridden = Settings(_env_file=None)
    assert overridden.rag.top_k == 3


def test_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(pydantic.ValidationError):
        RagConfig(chunk_size=100, chunk_overlap=100)


def test_negative_embedding_dimensions_rejected() -> None:
    with pytest.raises(pydantic.ValidationError):
        LLMConfig(embedding_dimensions=0)


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(pydantic.ValidationError) as excinfo:
        Settings(
            _env_file=None,
            app=AppConfig(env=AppEnv.production),
            auth=AuthConfig(jwt_secret="change-me-in-production"),
        )
    assert "JWT_SECRET" in str(excinfo.value)


def test_production_rejects_mock_llm_provider() -> None:
    with pytest.raises(pydantic.ValidationError):
        Settings(
            _env_file=None,
            app=AppConfig(env=AppEnv.production),
            auth=AuthConfig(jwt_secret="a-strong-secret-value"),
            llm=LLMConfig(provider="mock"),
        )


def test_security_summary_omits_secrets() -> None:
    settings = Settings(
        _env_file=None,
        llm=LLMConfig(anthropic_api_key="sk-ant-secret-value"),
        auth=AuthConfig(jwt_secret="super-secret-jwt"),
    )
    summary = settings.security_summary()
    assert summary["llm_provider"] == "mock"
    rendered = repr(summary)
    assert "sk-ant-secret-value" not in rendered
    assert "super-secret-jwt" not in rendered


def test_get_settings_is_cached_and_reload_clears() -> None:
    first = get_settings()
    assert get_settings() is first
    assert reload_settings() is not first
