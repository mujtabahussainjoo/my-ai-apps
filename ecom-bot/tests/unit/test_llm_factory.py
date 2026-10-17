"""Tests for LLM provider selection via the factory (TASK-013)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.config import LLMConfig, LLMProvider
from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.llm.factory import create_llm_client
from ecommerce_support.llm.providers import AnthropicLLMClient, MockLLMClient


def test_mock_provider_by_default() -> None:
    client = create_llm_client(LLMConfig())
    assert isinstance(client, MockLLMClient)
    assert client.model_name() == "claude-sonnet-4-5"


def test_mock_provider_uses_model_name() -> None:
    client = create_llm_client(LLMConfig(provider=LLMProvider.mock, model="mock-model"))
    assert isinstance(client, MockLLMClient)
    assert client.model_name() == "mock-model"


def test_anthropic_provider_selected() -> None:
    client = create_llm_client(
        LLMConfig(provider=LLMProvider.anthropic, anthropic_api_key="sk-test")
    )
    assert isinstance(client, AnthropicLLMClient)
    assert client.provider == "anthropic"
    assert client.model_name() == "claude-sonnet-4-5"


def test_anthropic_provider_requires_api_key() -> None:
    with pytest.raises(ConfigurationError):
        create_llm_client(LLMConfig(provider=LLMProvider.anthropic, anthropic_api_key=None))


def test_unimplemented_provider_fails_loudly() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        create_llm_client(LLMConfig(provider=LLMProvider.openai))
    assert excinfo.value.details["provider"] == "openai"


def test_router_role_uses_router_provider_and_model() -> None:
    config = LLMConfig(
        provider=LLMProvider.anthropic,
        anthropic_api_key="sk-test",
        router_provider=LLMProvider.mock,
        router_model="router-mock",
    )
    client = create_llm_client(config, role="router")
    assert isinstance(client, MockLLMClient)
    assert client.model_name() == "router-mock"


def test_router_role_falls_back_to_generation_model() -> None:
    config = LLMConfig(
        router_provider=LLMProvider.mock,
        router_model=None,
        model="gen-model",
    )
    client = create_llm_client(config, role="router")
    assert isinstance(client, MockLLMClient)
    assert client.model_name() == "gen-model"
