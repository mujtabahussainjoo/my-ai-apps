"""Provider registry.

Owns the catalogue of supported providers and the construction of provider
adapters. Selection of the *active* provider is handled by
:mod:`nexapilot.services.provider_settings`, which enforces the "exactly one
active provider" rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nexapilot.core.errors import ConfigurationError
from nexapilot.providers.anthropic import AnthropicProvider
from nexapilot.providers.base import Provider, ProviderCapabilities
from nexapilot.providers.gemini import GeminiProvider
from nexapilot.providers.ollama import OllamaProvider
from nexapilot.providers.openai import OpenAICompatibleProvider, OpenAIProvider


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    display_name: str
    requires_api_key: bool
    supports_custom_base_url: bool
    default_base_url: str
    default_model: str
    supported_auth_modes: tuple[str, ...]
    capabilities: ProviderCapabilities
    factory: type[Provider] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "requires_api_key": self.requires_api_key,
            "supports_custom_base_url": self.supports_custom_base_url,
            "default_base_url": self.default_base_url,
            "default_model": self.default_model,
            "supported_auth_modes": list(self.supported_auth_modes),
            "capabilities": self.capabilities.model_dump(),
        }


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        id="openai",
        display_name="OpenAI",
        requires_api_key=True,
        supports_custom_base_url=True,
        default_base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        supported_auth_modes=("api_key",),
        capabilities=ProviderCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=True,
            system_prompt=True,
            vision=True,
            max_context_tokens=128_000,
        ),
        factory=OpenAIProvider,
    ),
    "anthropic": ProviderSpec(
        id="anthropic",
        display_name="Anthropic Claude",
        requires_api_key=True,
        supports_custom_base_url=False,
        default_base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-5",
        supported_auth_modes=("api_key",),
        capabilities=ProviderCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=False,
            system_prompt=True,
            vision=True,
            max_context_tokens=200_000,
        ),
        factory=AnthropicProvider,
    ),
    "ollama": ProviderSpec(
        id="ollama",
        display_name="Ollama (local)",
        requires_api_key=False,
        supports_custom_base_url=True,
        default_base_url="http://127.0.0.1:11434",
        default_model="llama3.1",
        supported_auth_modes=("none",),
        capabilities=ProviderCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=False,
            system_prompt=True,
            vision=False,
            max_context_tokens=32_000,
        ),
        factory=OllamaProvider,
    ),
    "gemini": ProviderSpec(
        id="gemini",
        display_name="Google Gemini",
        requires_api_key=True,
        supports_custom_base_url=False,
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_model="gemini-2.0-flash",
        supported_auth_modes=("api_key",),
        capabilities=ProviderCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=True,
            system_prompt=True,
            vision=True,
            max_context_tokens=1_000_000,
        ),
        factory=GeminiProvider,
    ),
    "custom": ProviderSpec(
        id="custom",
        display_name="Custom OpenAI-compatible endpoint",
        requires_api_key=False,
        supports_custom_base_url=True,
        default_base_url="http://127.0.0.1:8000/v1",
        default_model="",
        supported_auth_modes=("api_key", "none"),
        capabilities=ProviderCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=False,
            system_prompt=True,
            vision=False,
            max_context_tokens=32_000,
        ),
        factory=OpenAICompatibleProvider,
    ),
}


def list_provider_specs() -> list[ProviderSpec]:
    return list(PROVIDER_SPECS.values())


def get_provider_spec(provider_id: str) -> ProviderSpec:
    spec = PROVIDER_SPECS.get(provider_id)
    if spec is None:
        raise ConfigurationError(
            f"Unknown provider '{provider_id}'",
            details={"supported": sorted(PROVIDER_SPECS)},
        )
    return spec


def build_provider(
    provider_id: str,
    *,
    model: str,
    base_url: str = "",
    api_key: str = "",
    transport: Any = None,
    timeout: float = 120.0,
) -> Provider:
    """Instantiate a provider adapter from a validated configuration."""
    spec = get_provider_spec(provider_id)
    factory = spec.factory
    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": base_url or spec.default_base_url,
        "api_key": api_key,
        "timeout": timeout,
    }
    if transport is not None:
        kwargs["transport"] = transport
    provider = factory(**kwargs)
    return provider
