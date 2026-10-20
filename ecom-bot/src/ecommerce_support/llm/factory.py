"""LLM client factory: the single place providers are selected by configuration.

Agents/tools get an :class:`~ecommerce_support.llm.base.LLMClient` from here and never import
provider SDKs. Switching providers is a config-only change (NFR-007, ACC-009).
"""

from __future__ import annotations

from typing import Literal

from ecommerce_support.core.config import LLMConfig, LLMProvider, get_settings
from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.llm.base import LLMClient
from ecommerce_support.llm.providers import (
    AnthropicLLMClient,
    GeminiLLMClient,
    MockLLMClient,
    OllamaLLMClient,
    OpenAICompatibleLLMClient,
    OpenAILLMClient,
)
from ecommerce_support.llm.retry import RetryingLLMClient, RetryPolicy
from ecommerce_support.llm.usage import UsageTracker, get_usage_tracker

ClientRole = Literal["generation", "router"]


def create_llm_client(
    config: LLMConfig,
    *,
    role: ClientRole = "generation",
    tracker: UsageTracker | None = None,
) -> LLMClient:
    """Build the provider client selected by ``config`` for ``role``.

    Providers are enabled one at a time via configuration (NFR-007, ACC-009). ``role="router"``
    uses the (optional) dedicated router provider/model so classification can run on a cheaper
    model without touching generation code.

    The returned client is wrapped in a :class:`RetryingLLMClient` that applies the configured
    per-call timeout, bounded retry/backoff policy, and token/cost tracking (TASK-015). Use
    ``client.unwrap()`` to reach the raw provider adapter.
    """
    provider_client = _build_provider_client(config, role=role)
    return RetryingLLMClient(
        provider_client,
        RetryPolicy.from_config(config),
        timeout_seconds=config.timeout_seconds,
        tracker=tracker if tracker is not None else get_usage_tracker(),
    )


def _build_provider_client(config: LLMConfig, *, role: ClientRole) -> LLMClient:
    if role == "router":
        provider = config.router_provider
        model = config.router_model or config.model
    else:
        provider = config.provider
        model = config.model
    timeout = config.timeout_seconds

    if provider is LLMProvider.mock:
        return MockLLMClient(name=model or "mock-1")

    if provider is LLMProvider.anthropic:
        return AnthropicLLMClient(
            model=model,
            api_key=config.anthropic_api_key,
            base_url=config.anthropic_base_url,
            timeout=timeout,
        )

    if provider is LLMProvider.openai:
        return OpenAILLMClient(
            model=model,
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            timeout=timeout,
        )

    if provider is LLMProvider.gemini:
        return GeminiLLMClient(
            model=model,
            api_key=config.google_api_key,
            timeout=timeout,
        )

    if provider is LLMProvider.ollama:
        return OllamaLLMClient(
            model=model,
            base_url=config.ollama_base_url,
            timeout=timeout,
        )

    if provider is LLMProvider.openai_compatible:
        return OpenAICompatibleLLMClient(
            model=config.openai_compatible_model or model,
            base_url=config.openai_compatible_base_url,
            api_key=config.openai_compatible_api_key,
            timeout=timeout,
        )

    raise ConfigurationError(
        f"LLM provider {provider.value!r} is not implemented yet.",
        details={"provider": provider.value, "role": role},
    )


def get_llm_client(*, role: ClientRole = "generation") -> LLMClient:
    """Convenience wrapper that builds a client from the process settings."""
    return create_llm_client(get_settings().llm, role=role)
