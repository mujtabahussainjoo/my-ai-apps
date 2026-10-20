"""Tests for the Anthropic adapter without network access (TASK-013).

We inject a fake transport-compatible client so request/response/stream mapping is exercised
offline; the real ``AsyncAnthropic`` construction path is covered by requiring an API key.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import anthropic
import httpx
import pytest
from anthropic import AsyncAnthropic
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from pydantic import BaseModel

from ecommerce_support.core.exceptions import (
    ConfigurationError,
    LLMError,
    LLMTimeoutError,
)
from ecommerce_support.llm.providers.anthropic import (
    AnthropicLLMClient,
    _to_anthropic_messages,
    _to_anthropic_tool_choice,
)
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


def _message(
    *blocks: Any,
    model: str = "claude-test",
    stop_reason: str | None = "end_turn",
    input_tokens: int = 3,
    output_tokens: int = 2,
) -> Message:
    return Message(
        id="msg_1",
        content=list(blocks),
        model=model,
        role="assistant",
        stop_reason=stop_reason,
        type="message",
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _FakeStream:
    def __init__(self, deltas: list[str], final: Message) -> None:
        self._deltas = deltas
        self._final = final

    async def __aenter__(self) -> _FakeStream:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    @property
    def text_stream(self) -> AsyncIterator[str]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[str]:
        for delta in self._deltas:
            yield delta

    async def get_final_message(self) -> Message:
        return self._final


class _FakeMessages:
    def __init__(self, message: Message, stream: _FakeStream | None = None) -> None:
        self._message = message
        self._stream = stream
        self.calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        return self._message

    def stream(self, **kwargs: Any) -> _FakeStream:
        self.stream_calls.append(kwargs)
        assert self._stream is not None
        return self._stream


class _FakeAnthropic:
    def __init__(self, messages: _FakeMessages) -> None:
        self.messages = messages
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _client(messages: _FakeMessages, **kwargs: Any) -> AnthropicLLMClient:
    return AnthropicLLMClient(
        model="claude-test",
        client=cast(AsyncAnthropic, _FakeAnthropic(messages)),
        **kwargs,
    )


def _request(*messages: ChatMessage, **kwargs: Any) -> CompletionRequest:
    return CompletionRequest(messages=list(messages), **kwargs)


# --- construction -----------------------------------------------------------


def test_requires_api_key_without_injected_client() -> None:
    with pytest.raises(ConfigurationError):
        AnthropicLLMClient(model="claude-test")


def test_requires_model() -> None:
    with pytest.raises(ConfigurationError):
        AnthropicLLMClient(model="", api_key="sk-test")


# --- complete ---------------------------------------------------------------


async def test_complete_maps_request_and_response() -> None:
    fake = _FakeMessages(_message(TextBlock(type="text", text="Hello there")))
    client = _client(fake)
    response = await client.complete(
        _request(
            ChatMessage(role=Role.system, content="be nice"),
            ChatMessage(role=Role.user, content="hi"),
            max_tokens=128,
            temperature=0.2,
            stop=["END"],
        )
    )
    assert response.content == "Hello there"
    assert response.finish_reason == "end_turn"
    assert response.usage.prompt_tokens == 3
    assert response.usage.completion_tokens == 2
    assert response.usage.total_tokens == 5

    (call,) = fake.calls
    assert call["model"] == "claude-test"
    assert call["max_tokens"] == 128
    assert call["temperature"] == pytest.approx(0.2)
    assert call["stop_sequences"] == ["END"]
    assert call["system"] == "be nice"
    assert call["messages"] == [{"role": "user", "content": "hi"}]


async def test_complete_request_model_override() -> None:
    fake = _FakeMessages(_message(TextBlock(type="text", text="x")))
    client = _client(fake)
    await client.complete(
        _request(ChatMessage(role=Role.user, content="hi"), model="claude-override")
    )
    assert fake.calls[0]["model"] == "claude-override"


# --- tool calling -----------------------------------------------------------


async def test_tool_call_returns_tool_calls() -> None:
    block = ToolUseBlock(type="tool_use", id="t1", name="lookup_order", input={"order_id": "1"})
    fake = _FakeMessages(_message(block, stop_reason="tool_use"))
    client = _client(fake)
    tools = [ToolDefinition(name="lookup_order", description="d", parameters={"type": "object"})]
    response = await client.tool_call(
        _request(ChatMessage(role=Role.user, content="where")), tools, tool_choice="required"
    )
    assert response.finish_reason == "tool_use"
    assert response.tool_calls == [
        ToolCall(id="t1", name="lookup_order", arguments={"order_id": "1"})
    ]
    call = fake.calls[0]
    assert call["tools"] == [
        {"name": "lookup_order", "description": "d", "input_schema": {"type": "object"}}
    ]
    assert call["tool_choice"] == {"type": "any"}


def test_tool_choice_mapping() -> None:
    assert _to_anthropic_tool_choice(None) is None
    assert _to_anthropic_tool_choice("auto") is None
    assert _to_anthropic_tool_choice("required") == {"type": "any"}
    assert _to_anthropic_tool_choice("none") == {"type": "none"}
    assert _to_anthropic_tool_choice("lookup_order") == {"type": "tool", "name": "lookup_order"}


# --- structured -------------------------------------------------------------


async def test_structured_forces_tool_and_validates() -> None:
    block = ToolUseBlock(
        type="tool_use",
        id="t1",
        name="emit_structured_output",
        input={"answer": "yes", "confidence": 0.9},
    )
    fake = _FakeMessages(_message(block, stop_reason="tool_use"))
    client = _client(fake)
    result = await client.structured(_request(ChatMessage(role=Role.user, content="q")), _Answer)
    assert result == _Answer(answer="yes", confidence=0.9)
    call = fake.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "emit_structured_output"}
    assert call["tools"][0]["name"] == "emit_structured_output"
    assert call["tools"][0]["input_schema"] == _Answer.model_json_schema()


async def test_structured_missing_tool_raises() -> None:
    fake = _FakeMessages(_message(TextBlock(type="text", text="nope")))
    client = _client(fake)
    with pytest.raises(LLMError):
        await client.structured(_request(ChatMessage(role=Role.user, content="q")), _Answer)


# --- streaming --------------------------------------------------------------


async def test_astream_yields_deltas_and_final_chunk() -> None:
    final = _message(TextBlock(type="text", text="hello"), input_tokens=4, output_tokens=1)
    fake = _FakeMessages(
        _message(TextBlock(type="text", text="x")), _FakeStream(["he", "llo"], final)
    )
    client = _client(fake)
    chunks = [
        chunk async for chunk in client.astream(_request(ChatMessage(role=Role.user, content="hi")))
    ]
    assert "".join(chunk.delta for chunk in chunks) == "hello"
    assert chunks[-1].done is True
    assert chunks[-1].finish_reason == "end_turn"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 5


# --- message mapping --------------------------------------------------------


def test_to_anthropic_messages_handles_tool_turns() -> None:
    request = _request(
        ChatMessage(role=Role.system, content="sys"),
        ChatMessage(role=Role.user, content="hi"),
        ChatMessage(
            role=Role.assistant,
            content="calling",
            tool_calls=[ToolCall(id="t1", name="lookup", arguments={"a": 1})],
        ),
        ChatMessage(role=Role.tool, content="result", tool_call_id="t1"),
    )
    mapped = _to_anthropic_messages(request)
    assert mapped[0] == {"role": "user", "content": "hi"}
    assert mapped[1]["role"] == "assistant"
    assert mapped[1]["content"] == [
        {"type": "text", "text": "calling"},
        {"type": "tool_use", "id": "t1", "name": "lookup", "input": {"a": 1}},
    ]
    assert mapped[2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "result"}],
    }


# --- error normalization ----------------------------------------------------


def _httpx_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


async def test_complete_normalizes_provider_error() -> None:
    class _BoomMessages:
        async def create(self, **kwargs: Any) -> Message:
            raise anthropic.APITimeoutError(request=_httpx_request())

    client = AnthropicLLMClient(
        model="claude-test",
        client=cast(AsyncAnthropic, _FakeAnthropic(cast(Any, _BoomMessages()))),
    )
    with pytest.raises(LLMTimeoutError):
        await client.complete(_request(ChatMessage(role=Role.user, content="hi")))


async def test_aclose_closes_client() -> None:
    fake = _FakeAnthropic(_FakeMessages(_message(TextBlock(type="text", text="x"))))
    client = AnthropicLLMClient(model="claude-test", client=cast(AsyncAnthropic, fake))
    await client.aclose()
    assert fake.closed is True
