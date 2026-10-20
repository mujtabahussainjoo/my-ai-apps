"""Tests for the Gemini adapter without network access (TASK-014)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from ecommerce_support.core.exceptions import ConfigurationError, LLMAuthError, LLMTimeoutError
from ecommerce_support.llm.capabilities import LLMCapability
from ecommerce_support.llm.providers.gemini import GeminiLLMClient
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


def _part(text: str | None = None, function_call: Any = None) -> SimpleNamespace:
    return SimpleNamespace(text=text, function_call=function_call)


def _response(
    *,
    texts: list[str] | None = None,
    function_calls: list[SimpleNamespace] | None = None,
    finish: str = "STOP",
    prompt: int = 3,
    completion: int = 2,
    total: int = 5,
    model_version: str = "gemini-test",
    parsed: Any = None,
    text: str | None = None,
) -> SimpleNamespace:
    parts = [_part(t) for t in (texts or [])]
    parts.extend(_part(function_call=fc) for fc in (function_calls or []))
    candidate = SimpleNamespace(
        finish_reason=SimpleNamespace(name=finish),
        content=SimpleNamespace(parts=parts),
    )
    return SimpleNamespace(
        candidates=[candidate],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=completion, total_token_count=total
        ),
        model_version=model_version,
        parsed=parsed,
        text=text,
    )


async def _aiter(items: list[Any]) -> Any:
    for item in items:
        yield item


class _FakeModels:
    def __init__(self, response: Any = None, chunks: list[Any] | None = None) -> None:
        self._response = response
        self._chunks = chunks or []
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response

    def generate_content_stream(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return _aiter(self._chunks)


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.aio = SimpleNamespace(models=models)


def _client(models: _FakeModels) -> GeminiLLMClient:
    return GeminiLLMClient(model="gemini-test", client=_FakeClient(models))


def _request(*messages: ChatMessage, **kwargs: Any) -> CompletionRequest:
    return CompletionRequest(messages=list(messages), **kwargs)


# --- construction -----------------------------------------------------------


def test_requires_api_key_without_client() -> None:
    with pytest.raises(ConfigurationError):
        GeminiLLMClient(model="gemini-test")


def test_requires_model() -> None:
    with pytest.raises(ConfigurationError):
        GeminiLLMClient(model="", api_key="key")


def test_supports_all_core_capabilities() -> None:
    client = GeminiLLMClient(model="gemini-test", client=_FakeClient(_FakeModels()))
    for capability in (
        LLMCapability.complete,
        LLMCapability.stream,
        LLMCapability.structured,
        LLMCapability.tool_calling,
    ):
        assert client.supports(capability)


# --- complete ---------------------------------------------------------------


async def test_complete_maps_response_and_config() -> None:
    models = _FakeModels(response=_response(texts=["Hi ", "there"]))
    client = _client(models)
    response = await client.complete(
        _request(
            ChatMessage(role=Role.system, content="be nice"),
            ChatMessage(role=Role.user, content="hi"),
            temperature=0.4,
            max_tokens=128,
        )
    )
    assert response.content == "Hi there"
    assert response.usage.total_tokens == 5
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    assert call["config"].system_instruction == "be nice"
    assert call["config"].temperature == pytest.approx(0.4)
    assert call["config"].max_output_tokens == 128


# --- streaming --------------------------------------------------------------


async def test_astream_yields_deltas_and_final() -> None:
    chunks = [
        _response(texts=["he"]),
        _response(texts=["llo"], finish="STOP", prompt=4, completion=1, total=5),
    ]
    models = _FakeModels(chunks=chunks)
    client = _client(models)
    got = [c async for c in client.astream(_request(ChatMessage(role=Role.user, content="hi")))]
    assert "".join(c.delta for c in got) == "hello"
    assert got[-1].done is True
    assert got[-1].finish_reason == "stop"
    assert got[-1].usage is not None
    assert got[-1].usage.total_tokens == 5


# --- structured -------------------------------------------------------------


async def test_structured_uses_parsed() -> None:
    parsed = _Answer(answer="yes", confidence=0.8)
    models = _FakeModels(response=_response(parsed=parsed))
    client = _client(models)
    result = await client.structured(_request(ChatMessage(role=Role.user, content="q")), _Answer)
    assert result == parsed
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is _Answer


async def test_structured_falls_back_to_json_text() -> None:
    models = _FakeModels(response=_response(text='{"answer":"ok","confidence":0.5}'))
    client = _client(models)
    result = await client.structured(_request(ChatMessage(role=Role.user, content="q")), _Answer)
    assert result == _Answer(answer="ok", confidence=0.5)


# --- tool calling -----------------------------------------------------------


async def test_tool_call_maps_function_calls() -> None:
    call = SimpleNamespace(id="t1", name="lookup_order", args={"order_id": "1"})
    models = _FakeModels(response=_response(function_calls=[call], finish="STOP"))
    client = _client(models)
    tools = [ToolDefinition(name="lookup_order", description="d", parameters={"type": "object"})]
    response = await client.tool_call(
        _request(ChatMessage(role=Role.user, content="where")), tools, tool_choice="required"
    )
    assert response.tool_calls == [
        ToolCall(id="t1", name="lookup_order", arguments={"order_id": "1"})
    ]
    config = models.calls[0]["config"]
    assert config.tools[0].function_declarations[0].name == "lookup_order"
    assert config.tool_config.function_calling_config.mode.value == "ANY"


# --- error normalization ----------------------------------------------------


async def test_complete_normalizes_timeout() -> None:
    class _Boom:
        def __init__(self) -> None:
            self.models = SimpleNamespace(generate_content=self._raise)

        async def _raise(self, **kwargs: Any) -> Any:
            raise TimeoutError("slow")

        @property
        def aio(self) -> SimpleNamespace:
            return SimpleNamespace(models=self.models)

    client = GeminiLLMClient(model="gemini-test", client=_Boom())
    with pytest.raises(LLMTimeoutError):
        await client.complete(_request(ChatMessage(role=Role.user, content="hi")))


async def test_complete_normalizes_auth_error() -> None:
    class _Auth(Exception):
        status_code = 401

    class _BoomAuth:
        def __init__(self) -> None:
            self.models = SimpleNamespace(generate_content=self._raise)

        async def _raise(self, **kwargs: Any) -> Any:
            raise _Auth("bad key")

        @property
        def aio(self) -> SimpleNamespace:
            return SimpleNamespace(models=self.models)

    client = GeminiLLMClient(model="gemini-test", client=_BoomAuth())
    with pytest.raises(LLMAuthError):
        await client.complete(_request(ChatMessage(role=Role.user, content="hi")))
