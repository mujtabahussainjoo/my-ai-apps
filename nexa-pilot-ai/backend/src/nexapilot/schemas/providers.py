"""Provider-related API schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexapilot.providers.base import ProviderCapabilities

AuthMode = Literal["api_key", "none", "bearer_optional", "managed_identity"]


class ProviderSpecSchema(BaseModel):
    """Static description of a supported provider."""

    id: str
    display_name: str
    requires_api_key: bool
    supports_custom_base_url: bool
    default_base_url: str
    default_model: str = ""
    supported_auth_modes: list[str]
    capabilities: ProviderCapabilities


class ProviderConfigRequest(BaseModel):
    """Payload for saving / activating a provider configuration."""

    provider: str
    model: str = Field(min_length=1, max_length=200)
    base_url: str = ""
    auth_mode: AuthMode = "api_key"
    api_key: str | None = None
    activate: bool = True

    @field_validator("provider")
    @classmethod
    def _provider_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("provider is required")
        return value.strip()


class ProviderConfigSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = ""
    provider: str
    model: str
    base_url: str = ""
    auth_mode: str = "api_key"
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    is_active: bool = False
    has_secret: bool = False
    secret_reference: str = ""


class ActiveProviderSchema(BaseModel):
    provider: str = ""
    model: str = ""
    base_url: str = ""
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    is_configured: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)
