"""Tests for the OpenAI-compatible adapter (TASK-014)."""

from __future__ import annotations

from typing import Any, cast

import pytest
from openai import AsyncOpenAI

from ecommerce_support.core.exceptions import ConfigurationError, LLMCapabilityError
from ecommerce_support.llm.providers.openai import OpenAILLMClient
from ecommerce_support.llm.providers.openai_compatible import OpenAICompatibleLLMClient
from ecommerce_support.llm.types import ChatMessage, CompletionRequest, Role


class _FakeAsyncOpenAI:
    async def close(self) -> None:
        return None


def _request(*messages: ChatMessage, **kwargs: Any) -> CompletionRequest:
    return CompletionRequest(messages=list(messages), **kwargs)


def test_requires_base_url_without_client() -> None:
    with pytest.raises(ConfigurationError):
        OpenAICompatibleLLMClient(model="local-model")


def test_requires_model() -> None:
    with pytest.raises(ConfigurationError):
        OpenAICompatibleLLMClient(model="", base_url="http://localhost:8000/v1")


def test_capabilities_exclude_structured() -> None:
    from ecommerce_support.llm.capabilities import LLMCapability

    client = OpenAICompatibleLLMClient(model="m", client=cast(AsyncOpenAI, _FakeAsyncOpenAI()))
    assert client.provider == "openai_compatible"
    assert client.supports(LLMCapability.tool_calling)
    assert not client.supports(LLMCapability.structured)


async def test_structured_fails_loudly() -> None:
    from pydantic import BaseModel

    from ecommerce_support.llm.capabilities import LLMCapability

    class _S(BaseModel):
        a: int

    client = OpenAICompatibleLLMClient(model="m", client=cast(AsyncOpenAI, _FakeAsyncOpenAI()))
    with pytest.raises(LLMCapabilityError):
        await client.structured(_request(ChatMessage(role=Role.user, content="q")), _S)
    # The require() check uses the matrix, not the adapter method.
    with pytest.raises(LLMCapabilityError):
        client.require(LLMCapability.structured)


def test_inherits_openai_base() -> None:
    assert issubclass(OpenAICompatibleLLMClient, OpenAILLMClient)
