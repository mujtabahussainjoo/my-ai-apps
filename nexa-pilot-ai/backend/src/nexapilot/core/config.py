"""Application configuration.

All runtime configuration is validated by Pydantic. Nothing else in the codebase
reads ``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings for the NexaPilot backend."""

    model_config = SettingsConfigDict(
        env_prefix="NEXAPILOT_",
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NexaPilot AI"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    host: str = "127.0.0.1"
    port: int = 8765

    # The backend is bound to loopback only. It exposes an API capable of acting on
    # the user's behalf, so it must never be reachable from the network.
    api_token: str = Field(default="", description="Optional shared token for local API auth")

    request_timeout_seconds: float = 120.0
    provider_timeout_seconds: float = 120.0
    provider_max_retries: int = 2

    max_tool_iterations: int = 12
    max_agent_steps: int = 24

    coding_workspace_root: str = ""
    coding_command_timeout_seconds: float = 120.0
    coding_max_output_bytes: int = 256_000

    database_url: str = ""
    secret_backend: Literal["keyring", "file", "memory"] = "keyring"

    web_search_provider: Literal["", "brave", "tavily", "searxng"] = ""
    web_search_api_key_ref: str = ""
    web_search_endpoint: str = ""

    travel_provider: Literal["", "amadeus", "rail-guidance"] = ""
    travel_api_key_ref: str = ""
    travel_api_secret_ref: str = ""
    travel_api_base_url: str = "https://test.api.amadeus.com"

    finance_provider: Literal["", "stooq", "yahoo"] = ""
    finance_api_key_ref: str = ""
    finance_broker_base_url: str = ""
    finance_broker_api_key_ref: str = ""
    finance_max_order_value: float = 10_000.0
    finance_max_order_quantity: int = 1_000

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1"

    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"

    google_oauth_client_id_ref: str = ""
    google_oauth_client_secret_ref: str = ""
    google_oauth_redirect_uri: str = "http://127.0.0.1:8765/api/accounts/google/callback"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        from nexapilot.core.paths import db_path

        return f"sqlite:///{db_path()}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings from the environment, then apply persisted UI overrides."""
    from nexapilot.core.settings_store import apply_overrides

    return apply_overrides(Settings())
