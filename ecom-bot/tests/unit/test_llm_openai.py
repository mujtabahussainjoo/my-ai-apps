"""Tests for the OpenAI adapter without network access (TASK-014)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ParsedChatCompletion,
    ParsedChatCompletionMessage,
    ParsedChoice,
)
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_chunk import Choice as ChunkChoice
from openai.types.chat.chat_completion_chunk import ChoiceDelta
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from openai.types.completion_usage import CompletionUsage
from pydantic import BaseModel

from ecommerce_support.core.exceptions import ConfigurationError, LLMError, LLMTimeoutError
from ecommerce_support.llm.providers.openai import OpenAILLMClient, _arguments_to_json
from ecommerce_support.llm.types import (
    ChatMessage,
    CompletionRequest,
    Role,
    ToolCall,
    ToolDefinition,
)


class _Answer(BaseModel):
    answer: str
    confidence: float


def _usage(prompt: int = 3, completion: int = 2) -> CompletionUsage:
    return CompletionUsage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def _completion(
    *,
    content: str | None = "Hello",
    tool_calls: list[ChatCompletionMessageToolCall] | None = None,
    finish_reason: str = "stop",
) -> ChatCompletion:
    message = ChatCompletionMessage(role="assistant", content=content, tool_calls=tool_calls)
    return ChatCompletion(
        id="c1",
        choices=[Choice(index=0, message=message, finish_reason=finish_reason)],
        created=1,
        model="gpt-test",
        object="chat.completion",
        usage=_usage(),
    )


def _chunk(
    content: str | None, finish: str | None = None, usage: CompletionUsage | None = None
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="c1",
        choices=[ChunkChoice(index=0, delta=ChoiceDelta(content=content), finish_reason=finish)],
        created=1,
        model="gpt-test",
        object="chat.completion.chunk",
        usage=usage,
    )


async def _aiter(items: list[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


class _FakeCompletions:
    def __init__(
        self,
        completion: ChatCompletion | None = None,
        parsed: ParsedChatCompletion | None = None,
        chunks: list[ChatCompletionChunk] | None = None,
    ) -> None:
        self._completion = completion
        self._parsed = parsed
        self._chunks = chunks or []
        self.calls: list[dict[str, Any]] = []
        self.parse_calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return _aiter(self._chunks)
        return self._completion

    async def parse(self, **kwargs: Any) -> ParsedChatCompletion:
        self.parse_calls.append(kwargs)
        assert self._parsed is not None
        return self._parsed


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeAsyncOpenAI:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _client(completions: _FakeCompletions) -> OpenAILLMClient:
    return OpenAILLMClient(
        model="gpt-test", client=cast(AsyncOpenAI, _FakeAsyncOpenAI(completions))
    )


def _request(*messages: ChatMessage, **kwargs: Any) -> CompletionRequest:
    return CompletionRequest(messages=list(messages), **kwargs)


# --- construction -----------------------------------------------------------


def test_requires_api_key_without_injected_client() -> None:
    with pytest.raises(ConfigurationError):
        OpenAILLMClient(model="gpt-test")


def test_requires_model() -> None:
    with pytest.raises(ConfigurationError):
        OpenAILLMClient(model="", api_key="sk-test")


# --- complete ---------------------------------------------------------------


async def test_complete_maps_request_and_response() -> None:
    fake = _FakeCompletions(completion=_completion(content="Hi there"))
    client = _client(fake)
    response = await client.complete(
        _request(
            ChatMessage(role=Role.system, content="be nice"),
            ChatMessage(role=Role.user, content="hi"),
            max_tokens=64,
            temperature=0.3,
            stop=["END"],
        )
    )
    assert response.content == "Hi there"
    assert response.finish_reason == "stop"
    assert response.usage.total_tokens == 5

    call = fake.calls[0]
    assert call["model"] == "gpt-test"
    assert call["max_tokens"] == 64
    assert call["temperature"] == pytest.approx(0.3)
    assert call["stop"] == ["END"]
    assert call["messages"][0] == {"role": "system", "content": "be nice"}
    assert call["messages"][1] == {"role": "user", "content": "hi"}


async def test_complete_request_model_override() -> None:
    fake = _FakeCompletions(completion=_completion())
    client = _client(fake)
    await client.complete(_request(ChatMessage(role=Role.user, content="hi"), model="gpt-override"))
    assert fake.calls[0]["model"] == "gpt-override"


# --- tool calling -----------------------------------------------------------


async def test_tool_call_returns_tool_calls() -> None:
    tool_call = ChatCompletionMessageToolCall(
        id="t1",
        type="function",
        function=Function(name="lookup_order", arguments='{"order_id": "1"}'),
    )
    fake = _FakeCompletions(
        completion=_completion(content=None, tool_calls=[tool_call], finish_reason="tool_calls")
    )
    client = _client(fake)
    tools = [ToolDefinition(name="lookup_order", description="d", parameters={"type": "object"})]
    response = await client.tool_call(
        _request(ChatMessage(role=Role.user, content="where")), tools, tool_choice="required"
    )
    assert response.tool_calls == [
        ToolCall(id="t1", name="lookup_order", arguments={"order_id": "1"})
    ]
    assert response.finish_reason == "tool_calls"
    call = fake.calls[0]
    assert call["tools"][0]["type"] == "function"
    assert call["tools"][0]["function"]["name"] == "lookup_order"
    assert call["tool_choice"] == "required"


def test_arguments_parse_failure_falls_back() -> None:
    assert _arguments_to_json("{bad") == {"_raw": "{bad"}
    assert _arguments_to_json(None) == {}
    assert _arguments_to_json('{"a":1}') == {"a": 1}


# --- structured -------------------------------------------------------------


async def test_structured_uses_parse_and_returns_parsed() -> None:
    parsed = _Answer(answer="yes", confidence=0.9)
    message = ParsedChatCompletionMessage(role="assistant", parsed=parsed)
    parsed_completion = ParsedChatCompletion(
        id="c1",
        choices=[ParsedChoice(index=0, message=message, finish_reason="stop")],
        created=1,
        model="gpt-test",
        object="chat.completion",
    )
    fake = _FakeCompletions(parsed=parsed_completion)
    client = _client(fake)
    result = await client.structured(_request(ChatMessage(role=Role.user, content="q")), _Answer)
    assert result == parsed
    assert fake.parse_calls[0]["response_format"] is _Answer


async def test_structured_missing_parsed_raises() -> None:
    message = ParsedChatCompletionMessage(role="assistant", parsed=None)
    parsed_completion = ParsedChatCompletion(
        id="c1",
        choices=[ParsedChoice(index=0, message=message, finish_reason="stop")],
        created=1,
        model="gpt-test",
        object="chat.completion",
    )
    fake = _FakeCompletions(parsed=parsed_completion)
    client = _client(fake)
    with pytest.raises(LLMError):
        await client.structured(_request(ChatMessage(role=Role.user, content="q")), _Answer)


# --- streaming --------------------------------------------------------------


async def test_astream_yields_deltas_and_final_chunk() -> None:
    chunks = [
        _chunk("he"),
        _chunk("llo"),
        _chunk(None, finish="stop", usage=_usage(4, 1)),
    ]
    fake = _FakeCompletions(chunks=chunks)
    client = _client(fake)
    got = [c async for c in client.astream(_request(ChatMessage(role=Role.user, content="hi")))]
    assert "".join(c.delta for c in got) == "hello"
    assert got[-1].done is True
    assert got[-1].finish_reason == "stop"
    assert got[-1].usage is not None
    assert got[-1].usage.total_tokens == 5
    assert fake.calls[0]["stream"] is True
    assert fake.calls[0]["include_usage"] is True


# --- error normalization ----------------------------------------------------


async def test_complete_normalizes_timeout() -> None:
    class _Boom:
        async def create(self, **kwargs: Any) -> Any:
            raise TimeoutError("took too long")

    client = OpenAILLMClient(
        model="gpt-test", client=cast(AsyncOpenAI, _FakeAsyncOpenAI(cast(Any, _Boom())))
    )
    with pytest.raises(LLMTimeoutError):
        await client.complete(_request(ChatMessage(role=Role.user, content="hi")))


async def test_aclose_closes_client() -> None:
    fake = _FakeAsyncOpenAI(_FakeCompletions(completion=_completion()))
    client = OpenAILLMClient(model="gpt-test", client=cast(AsyncOpenAI, fake))
    await client.aclose()
    assert fake.closed is True
