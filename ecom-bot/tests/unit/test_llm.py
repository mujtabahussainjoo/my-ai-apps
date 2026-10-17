"""Tests for the provider-independent LLM interface and the mock provider (TASK-012)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from pydantic import BaseModel

from ecommerce_support.core.exceptions import LLMCapabilityError, LLMError
from ecommerce_support.llm import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    LLMCapability,
    LLMClient,
    Role,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    ensure_capability,
)
from ecommerce_support.llm.providers import MockLLMClient


class _Answer(BaseModel):
    answer: str
    confidence: float


def _user_request(content: str = "hello world") -> CompletionRequest:
    return CompletionRequest(messages=[ChatMessage(role=Role.user, content=content)])


# --- interface --------------------------------------------------------------


def test_llm_client_is_abstract() -> None:
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def test_incomplete_subclass_cannot_instantiate() -> None:
    class OnlyComplete(LLMClient):
        async def complete(self, request: CompletionRequest) -> CompletionResponse:
            return CompletionResponse(model="x")

    with pytest.raises(TypeError):
        OnlyComplete()  # type: ignore[abstract]


def test_ensure_capability_ok() -> None:
    ensure_capability({LLMCapability.complete}, LLMCapability.complete, provider="p")


def test_ensure_capability_raises_with_details() -> None:
    with pytest.raises(LLMCapabilityError) as excinfo:
        ensure_capability(set(), LLMCapability.stream, provider="p")
    assert excinfo.value.code == "llm_capability_error"
    assert excinfo.value.details == {"provider": "p", "capability": "stream"}
    assert excinfo.value.retryable is False


# --- mock: capability surface ----------------------------------------------


def test_mock_declares_all_contracts() -> None:
    client = MockLLMClient()
    assert client.provider == "mock"
    for capability in (
        LLMCapability.complete,
        LLMCapability.stream,
        LLMCapability.structured,
        LLMCapability.tool_calling,
    ):
        assert client.supports(capability)
        client.require(capability)


def test_capability_error_when_unsupported() -> None:
    class CompleteOnly(MockLLMClient):
        capabilities = frozenset({LLMCapability.complete})

    client = CompleteOnly()
    assert client.supports(LLMCapability.complete)
    with pytest.raises(LLMCapabilityError):
        client.require(LLMCapability.stream)


# --- mock: complete ---------------------------------------------------------


async def test_complete_echoes_last_user_message() -> None:
    client = MockLLMClient(name="mock-7")
    response = await client.complete(_user_request("hello world"))
    assert response.content == "[mock] hello world"
    assert response.model == "mock-7"
    assert response.finish_reason == "stop"
    assert response.usage.prompt_tokens == 2
    assert response.usage.completion_tokens == 3
    assert response.usage.total_tokens == 5
    assert client.requests == [_user_request("hello world")]


async def test_complete_uses_scripted_response() -> None:
    client = MockLLMClient(completions=["first", "second"])
    assert (await client.complete(_user_request("a"))).content == "first"
    assert (await client.complete(_user_request("b"))).content == "second"


async def test_complete_prefers_request_model() -> None:
    client = MockLLMClient(name="mock-1")
    response = await client.complete(_user_request("hi").model_copy(update={"model": "override"}))
    assert response.model == "override"


# --- mock: astream ----------------------------------------------------------


async def test_astream_reassembles_and_terminates() -> None:
    client = MockLLMClient(chunk_size=4, completions=["abcdefghij"])
    chunks = [chunk async for chunk in client.astream(_user_request("x"))]
    streamed = "".join(chunk.delta for chunk in chunks)
    assert streamed == "abcdefghij"
    assert all(len(chunk.delta) <= 4 for chunk in chunks)
    assert chunks[-1].done is True
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert client.requests == [_user_request("x")]


async def test_astream_is_async_iterator() -> None:
    client = MockLLMClient()
    stream = client.astream(_user_request("hi"))
    assert isinstance(stream, AsyncIterator)


async def test_astream_default_content() -> None:
    client = MockLLMClient(chunk_size=1)
    chunks = [chunk async for chunk in client.astream(_user_request("yo"))]
    assert "".join(c.delta for c in chunks) == "[mock] yo"


# --- mock: structured -------------------------------------------------------


async def test_structured_returns_scripted_model() -> None:
    expected = _Answer(answer="yes", confidence=0.9)
    client = MockLLMClient(structured_outputs=[expected])
    result = await client.structured(_user_request("q"), _Answer)
    assert result == expected
    assert len(client.structured_requests) == 1


async def test_structured_validates_dict() -> None:
    client = MockLLMClient(structured_outputs=[{"answer": "ok", "confidence": 0.5}])
    result = await client.structured(_user_request("q"), _Answer)
    assert result == _Answer(answer="ok", confidence=0.5)


async def test_structured_without_script_raises() -> None:
    client = MockLLMClient()
    with pytest.raises(LLMError) as excinfo:
        await client.structured(_user_request("q"), _Answer)
    assert excinfo.value.details == {"schema": "_Answer"}


async def test_structured_wrong_type_raises() -> None:
    class Other(BaseModel):
        value: int

    client = MockLLMClient(structured_outputs=[Other(value=1)])
    with pytest.raises(LLMError):
        await client.structured(_user_request("q"), _Answer)


# --- mock: tool calling -----------------------------------------------------


async def test_tool_call_returns_scripted_calls() -> None:
    call = ToolCall(id="c1", name="lookup_order", arguments={"order_id": "O-1"})
    client = MockLLMClient(tool_call_responses=[[call]])
    tools = [ToolDefinition(name="lookup_order", description="look up an order")]
    response = await client.tool_call(_user_request("where is my order"), tools)
    assert response.tool_calls == [call]
    assert response.finish_reason == "tool_calls"
    assert response.content == ""
    assert client.tool_requests == [(_user_request("where is my order"), tuple(tools))]


async def test_tool_call_without_script_returns_empty() -> None:
    client = MockLLMClient()
    response = await client.tool_call(_user_request("hi"), [])
    assert response.tool_calls == []
    assert response.finish_reason == "stop"


async def test_aclose_is_noop() -> None:
    client = MockLLMClient()
    assert await client.aclose() is None


def test_bad_chunk_size_rejected() -> None:
    with pytest.raises(ValueError):
        MockLLMClient(chunk_size=0)


def test_stream_chunk_defaults() -> None:
    chunk = StreamChunk()
    assert chunk.delta == ""
    assert chunk.done is False
    assert chunk.finish_reason is None
