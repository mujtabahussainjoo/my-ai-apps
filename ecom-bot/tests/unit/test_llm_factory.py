"""Tests for LLM provider selection via the factory (TASK-013, TASK-014, TASK-015)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.config import LLMConfig, LLMProvider
from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.llm.factory import create_llm_client
from ecommerce_support.llm.providers import (
    AnthropicLLMClient,
    GeminiLLMClient,
    MockLLMClient,
    OllamaLLMClient,
    OpenAICompatibleLLMClient,
    OpenAILLMClient,
)
from ecommerce_support.llm.retry import RetryingLLMClient, RetryPolicy


def test_mock_provider_by_default() -> None:
    client = create_llm_client(LLMConfig())
    assert isinstance(client, RetryingLLMClient)
    assert isinstance(client.unwrap(), MockLLMClient)
    assert client.model_name() == "claude-sonnet-4-5"


def test_factory_wraps_with_configured_retry_and_timeout() -> None:
    config = LLMConfig(max_retries=5, timeout_seconds=12.0, retry_backoff_base_seconds=0.1)
    client = create_llm_client(config)
    assert isinstance(client, RetryingLLMClient)
    assert client._policy == RetryPolicy(max_attempts=5, base_seconds=0.1, max_seconds=8.0)
    assert client._timeout_seconds == 12.0


def test_mock_provider_uses_model_name() -> None:
    client = create_llm_client(LLMConfig(provider=LLMProvider.mock, model="mock-model"))
    assert isinstance(client.unwrap(), MockLLMClient)
    assert client.model_name() == "mock-model"


def test_anthropic_provider_selected() -> None:
    client = create_llm_client(
        LLMConfig(provider=LLMProvider.anthropic, anthropic_api_key="sk-test")
    )
    inner = client.unwrap()
    assert isinstance(inner, AnthropicLLMClient)
    assert inner.provider == "anthropic"
    assert client.model_name() == "claude-sonnet-4-5"


def test_anthropic_provider_requires_api_key() -> None:
    with pytest.raises(ConfigurationError):
        create_llm_client(LLMConfig(provider=LLMProvider.anthropic, anthropic_api_key=None))


def test_openai_provider_selected() -> None:
    client = create_llm_client(LLMConfig(provider=LLMProvider.openai, openai_api_key="sk-test"))
    inner = client.unwrap()
    assert isinstance(inner, OpenAILLMClient)
    assert inner.provider == "openai"


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(ConfigurationError):
        create_llm_client(LLMConfig(provider=LLMProvider.openai, openai_api_key=None))


def test_gemini_provider_selected() -> None:
    client = create_llm_client(LLMConfig(provider=LLMProvider.gemini, google_api_key="g-test"))
    inner = client.unwrap()
    assert isinstance(inner, GeminiLLMClient)
    assert inner.provider == "gemini"


def test_gemini_provider_requires_api_key() -> None:
    with pytest.raises(ConfigurationError):
        create_llm_client(LLMConfig(provider=LLMProvider.gemini, google_api_key=None))


def test_ollama_provider_selected_without_key() -> None:
    client = create_llm_client(
        LLMConfig(provider=LLMProvider.ollama, model="llama3", ollama_base_url="http://o:11434")
    )
    inner = client.unwrap()
    assert isinstance(inner, OllamaLLMClient)
    assert inner.provider == "ollama"
    assert client.model_name() == "llama3"


def test_openai_compatible_provider_selected() -> None:
    client = create_llm_client(
        LLMConfig(
            provider=LLMProvider.openai_compatible,
            model="fallback",
            openai_compatible_base_url="http://vllm:8000/v1",
            openai_compatible_model="local-model",
        )
    )
    inner = client.unwrap()
    assert isinstance(inner, OpenAICompatibleLLMClient)
    assert inner.provider == "openai_compatible"
    assert client.model_name() == "local-model"


def test_openai_compatible_provider_requires_base_url() -> None:
    with pytest.raises(ConfigurationError):
        create_llm_client(
            LLMConfig(provider=LLMProvider.openai_compatible, openai_compatible_base_url=None)
        )


def test_router_role_uses_router_provider_and_model() -> None:
    config = LLMConfig(
        provider=LLMProvider.anthropic,
        anthropic_api_key="sk-test",
        router_provider=LLMProvider.mock,
        router_model="router-mock",
    )
    client = create_llm_client(config, role="router")
    assert isinstance(client.unwrap(), MockLLMClient)
    assert client.model_name() == "router-mock"


def test_router_role_falls_back_to_generation_model() -> None:
    config = LLMConfig(
        router_provider=LLMProvider.mock,
        router_model=None,
        model="gen-model",
    )
    client = create_llm_client(config, role="router")
    assert isinstance(client.unwrap(), MockLLMClient)
    assert client.model_name() == "gen-model"


def test_supports_and_require_delegate_to_inner() -> None:
    from ecommerce_support.core.exceptions import LLMCapabilityError
    from ecommerce_support.llm.capabilities import LLMCapability

    client = create_llm_client(LLMConfig(provider=LLMProvider.anthropic, anthropic_api_key="k"))
    assert client.supports(LLMCapability.complete)
    with pytest.raises(LLMCapabilityError):
        client.require(LLMCapability.vision)
