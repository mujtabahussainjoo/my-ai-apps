"""Validated application configuration.

Loading model (single entry point for the whole application):

    defaults (model fields)
      < ``config/*.yaml``      (structure, committed)
      < ``.env`` / environment (overrides, secrets)

Environment variables override nested YAML values using the ``__`` delimiter, e.g.
``APP__LOG_LEVEL=debug``, ``DATABASE__URL=...``, ``INTEGRATIONS__JIRA_BASE_URL=...``.
Only this module reads ``os.environ`` (per AGENTS.md); everything else uses
:func:`get_settings`.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"


class AppEnv(StrEnum):
    development = "development"
    test = "test"
    staging = "staging"
    production = "production"


class LogLevel(StrEnum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"


class LogFormat(StrEnum):
    structured = "structured"
    plain = "plain"


class LLMProvider(StrEnum):
    mock = "mock"
    anthropic = "anthropic"
    openai = "openai"
    gemini = "gemini"
    ollama = "ollama"
    openai_compatible = "openai_compatible"


class EmbeddingProvider(StrEnum):
    mock = "mock"
    openai = "openai"
    ollama = "ollama"
    huggingface = "huggingface"


class TicketingProvider(StrEnum):
    mock = "mock"
    jira = "jira"
    servicenow = "servicenow"
    both = "both"
    none = "none"


class CommerceProvider(StrEnum):
    mock = "mock"


class GuardrailAction(StrEnum):
    block = "block"
    flag = "flag"


class AppConfig(BaseModel):
    env: AppEnv = AppEnv.development
    debug: bool = False
    log_level: LogLevel = LogLevel.info
    log_format: LogFormat = LogFormat.structured
    service_host: str = "0.0.0.0"
    service_port: int = Field(default=8000, ge=1, le=65535)


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://ecombot:ecombot@localhost:5434/ecombot"
    echo: bool = False
    pool_size: int = Field(default=10, ge=1)
    max_overflow: int = Field(default=20, ge=0)


class AuthConfig(BaseModel):
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = Field(default=60, ge=1)


class LimitsConfig(BaseModel):
    rate_limit_per_minute: int = Field(default=60, ge=1)
    max_message_chars: int = Field(default=4000, ge=1)
    max_document_bytes: int = Field(default=10 * 1024 * 1024, ge=1)


class ObservabilityConfig(BaseModel):
    tracing_enabled: bool = False
    langsmith_tracing: bool = False
    langsmith_project: str = "ecommerce-support"
    langsmith_api_key: str | None = None


class IntegrationsConfig(BaseModel):
    commerce_provider: CommerceProvider = CommerceProvider.mock
    ticketing_provider: TicketingProvider = TicketingProvider.mock
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None
    jira_issue_type: str = "Ticket"
    servicenow_instance: str | None = None
    servicenow_username: str | None = None
    servicenow_password: str | None = None
    servicenow_table: str = "incident"


class LLMConfig(BaseModel):
    provider: LLMProvider = LLMProvider.mock
    model: str = "claude-sonnet-4-5"
    router_provider: LLMProvider = LLMProvider.mock
    router_model: str | None = None
    embedding_provider: EmbeddingProvider = EmbeddingProvider.mock
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_base_seconds: float = Field(default=0.5, gt=0)
    retry_backoff_max_seconds: float = Field(default=8.0, gt=0)
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    google_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: str | None = None
    openai_compatible_model: str | None = None


class AgentsConfig(BaseModel):
    max_graph_iterations: int = Field(default=8, ge=1, le=50)
    max_routing_hops: int = Field(default=3, ge=1, le=10)
    max_retry_attempts: int = Field(default=2, ge=0, le=5)
    worker_timeout_seconds: float = Field(default=30.0, gt=0)
    enable_llm_router: bool = True


class RagConfig(BaseModel):
    top_k: int = Field(default=5, ge=1, le=50)
    distance_metric: str = "cosine"
    distance_threshold: float = Field(default=0.35, ge=0.0, le=2.0)
    chunk_size: int = Field(default=1000, ge=100)
    chunk_overlap: int = Field(default=150, ge=0)
    rerank_enabled: bool = False
    rerank_top_n: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def _overlap_lt_size(self) -> RagConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("rag.chunk_overlap must be smaller than rag.chunk_size")
        return self


class GuardrailsConfig(BaseModel):
    enabled: bool = True
    prompt_injection_action: GuardrailAction = GuardrailAction.block
    redact_pii_in_logs: bool = True
    redact_pii_in_tickets: bool = True
    max_prompt_injection_score: float = Field(default=0.7, ge=0.0, le=1.0)
    refuse_high_impact_actions: bool = True


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` (override wins), returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class YamlDirConfigSettingsSource(PydanticBaseSettingsSource):
    """Loads and merges every ``*.yaml`` in a config directory (sorted, later wins)."""

    def __init__(self, settings_cls: type[BaseSettings], config_dir: Path) -> None:
        super().__init__(settings_cls)
        self._config_dir = config_dir

    def _load(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if not self._config_dir.is_dir():
            return merged
        for path in sorted(self._config_dir.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"config file {path} must contain a YAML mapping")
            merged = _deep_merge(merged, raw)
        return merged

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        # Not used: we implement __call__ to return the full merged mapping.
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._load()


class Settings(BaseSettings):
    """Root settings object composed of validated config groups."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app: AppConfig = Field(default_factory=AppConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        config_dir = Path(os.environ.get("CONFIG_DIR", str(DEFAULT_CONFIG_DIR)))
        yaml_settings = YamlDirConfigSettingsSource(settings_cls, config_dir)
        # Earlier sources take precedence: explicit args > env > .env > yaml > secrets files.
        return (init_settings, env_settings, dotenv_settings, yaml_settings, file_secret_settings)

    @model_validator(mode="after")
    def _validate_environment(self) -> Settings:
        if self.app.env is AppEnv.production:
            if self.auth.jwt_secret == "change-me-in-production":
                raise ValueError(
                    "AUTH__JWT_SECRET must be set to a strong value in production "
                    "(refusing the default placeholder)."
                )
            if self.app.debug:
                raise ValueError("APP__DEBUG must be false in production.")
            if self.llm.provider is LLMProvider.mock:
                raise ValueError("LLM__PROVIDER=mock is not allowed in production.")
        return self

    def security_summary(self) -> dict[str, Any]:
        """Non-secret configuration summary for startup logging."""
        return {
            "env": self.app.env.value,
            "debug": self.app.debug,
            "log_level": self.app.log_level.value,
            "service": f"{self.app.service_host}:{self.app.service_port}",
            "llm_provider": self.llm.provider.value,
            "llm_model": self.llm.model,
            "embedding_provider": self.llm.embedding_provider.value,
            "commerce_provider": self.integrations.commerce_provider.value,
            "ticketing_provider": self.integrations.ticketing_provider.value,
            "tracing_enabled": self.observability.tracing_enabled,
            "guardrails_enabled": self.guardrails.enabled,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (cached)."""
    return Settings()


def reload_settings() -> Settings:
    """Clear the cache and rebuild settings (used by tests and long-running reloads)."""
    get_settings.cache_clear()
    return get_settings()
