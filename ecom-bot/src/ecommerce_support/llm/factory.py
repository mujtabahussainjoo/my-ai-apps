"""LLM client factory: the single place providers are selected by configuration.

Agents/tools get an :class:`~ecommerce_support.llm.base.LLMClient` from here and never import
provider SDKs. Switching providers is a config-only change (NFR-007, ACC-009).
"""

from __future__ import annotations

from typing import Literal

from ecommerce_support.core.config import LLMConfig, LLMProvider, get_settings
from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.llm.base import LLMClient
from ecommerce_support.llm.providers import AnthropicLLMClient, MockLLMClient

ClientRole = Literal["generation", "router"]


def create_llm_client(config: LLMConfig, *, role: ClientRole = "generation") -> LLMClient:
    """Build the provider client selected by ``config`` for ``role``.

    ``role="router"`` uses the (optional) dedicated router provider/model so classification
    can run on a cheaper model without touching generation code.
    """
    if role == "router":
        provider = config.router_provider
        model = config.router_model or config.model
    else:
        provider = config.provider
        model = config.model

    if provider is LLMProvider.mock:
        return MockLLMClient(name=model or "mock-1")

    if provider is LLMProvider.anthropic:
        return AnthropicLLMClient(
            model=model,
            api_key=config.anthropic_api_key,
            base_url=config.anthropic_base_url,
            timeout=config.timeout_seconds,
        )

    raise ConfigurationError(
        f"LLM provider {provider.value!r} is not implemented yet.",
        details={"provider": provider.value, "role": role},
    )


def get_llm_client(*, role: ClientRole = "generation") -> LLMClient:
    """Convenience wrapper that builds a client from the process settings."""
    return create_llm_client(get_settings().llm, role=role)
