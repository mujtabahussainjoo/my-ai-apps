"""Tests for the per-provider LLM capability matrix and enforcement (TASK-014)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.config import LLMProvider
from ecommerce_support.core.exceptions import ConfigurationError, LLMCapabilityError
from ecommerce_support.llm.capabilities import (
    PROVIDER_CAPABILITIES,
    LLMCapability,
    capabilities_for,
    ensure_capability,
    unsupported,
)
from ecommerce_support.llm.providers import (
    AnthropicLLMClient,
    GeminiLLMClient,
    MockLLMClient,
    OllamaLLMClient,
    OpenAICompatibleLLMClient,
    OpenAILLMClient,
)

_CORE = frozenset(
    {
        LLMCapability.complete,
        LLMCapability.stream,
        LLMCapability.structured,
        LLMCapability.tool_calling,
    }
)
_TOOLS_AND_STREAM = frozenset(
    {LLMCapability.complete, LLMCapability.stream, LLMCapability.tool_calling}
)


def test_every_config_provider_has_a_matrix_entry() -> None:
    for provider in LLMProvider:
        assert provider.value in PROVIDER_CAPABILITIES
        assert isinstance(capabilities_for(provider.value), frozenset)


def test_unknown_provider_raises() -> None:
    with pytest.raises(ConfigurationError):
        capabilities_for("bogus")


def test_full_capability_providers() -> None:
    for provider in ("mock", "anthropic", "openai", "gemini"):
        assert capabilities_for(provider) == _CORE


def test_conservative_capability_providers() -> None:
    for provider in ("ollama", "openai_compatible"):
        assert capabilities_for(provider) == _TOOLS_AND_STREAM
        assert unsupported(provider, LLMCapability.structured)


def test_no_provider_declares_vision() -> None:
    for provider in PROVIDER_CAPABILITIES:
        assert unsupported(provider, LLMCapability.vision)


def test_adapter_capabilities_match_matrix() -> None:
    assert MockLLMClient().capabilities == capabilities_for("mock")
    assert AnthropicLLMClient(model="m", api_key="k").capabilities == capabilities_for("anthropic")
    assert OpenAILLMClient(model="m", api_key="k").capabilities == capabilities_for("openai")
    assert GeminiLLMClient(model="m", api_key="k").capabilities == capabilities_for("gemini")
    assert OllamaLLMClient(model="m").capabilities == capabilities_for("ollama")
    assert OpenAICompatibleLLMClient(model="m", base_url="http://x").capabilities == (
        capabilities_for("openai_compatible")
    )


def test_require_raises_for_unsupported_capability() -> None:
    anthropic = AnthropicLLMClient(model="m", api_key="k")
    with pytest.raises(LLMCapabilityError) as excinfo:
        anthropic.require(LLMCapability.vision)
    assert excinfo.value.details == {"provider": "anthropic", "capability": "vision"}
    assert excinfo.value.retryable is False


def test_structured_gap_fails_loudly_for_ollama_and_compatible() -> None:
    ollama = OllamaLLMClient(model="m")
    with pytest.raises(LLMCapabilityError):
        ollama.require(LLMCapability.structured)
    compatible = OpenAICompatibleLLMClient(model="m", base_url="http://x")
    with pytest.raises(LLMCapabilityError):
        compatible.require(LLMCapability.structured)


def test_ensure_capability_accepts_supported() -> None:
    ensure_capability(_CORE, LLMCapability.structured, provider="openai")
