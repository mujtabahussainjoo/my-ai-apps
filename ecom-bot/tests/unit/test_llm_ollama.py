"""Tests for the Ollama adapter over a mocked HTTP transport (TASK-014)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from ecommerce_support.core.exceptions import (
    ConfigurationError,
    LLMAuthError,
    LLMCapabilityError,
)
from ecommerce_support.llm.capabilities import LLMCapability
from ecommerce_support.llm.providers.ollama import OllamaLLMClient
from ecommerce_support.llm.types import (
    ChatMessage,
    CompletionRequest,
    Role,
    ToolCall,
    ToolDefinition,
)


def _request(*messages: ChatMessage, **kwargs: Any) -> CompletionRequest:
    return CompletionRequest(messages=list(messages), **kwargs)


def _make_client(handler: Any) -> OllamaLLMClient:
    transport = httpx.MockTransport(handler)
    return OllamaLLMClient(
        model="llama3",
        client=httpx.AsyncClient(transport=transport, base_url="http://ollama"),
    )


def _ok_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if body.get("stream"):
        lines = [
            json.dumps({"message": {"role": "assistant", "content": "he"}, "done": False}),
            json.dumps({"message": {"role": "assistant", "content": "llo"}, "done": False}),
            json.dumps(
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 4,
                    "eval_count": 1,
                }
            ),
        ]
        return httpx.Response(200, content=("\n".join(lines) + "\n").encode())
    if body.get("tools"):
        return httpx.Response(
            200,
            json={
                "model": "llama3",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "lookup_order", "arguments": {"order_id": "1"}}}
                    ],
                },
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 3,
                "eval_count": 1,
            },
        )
    return httpx.Response(
        200,
        json={
            "model": "llama3",
            "message": {"role": "assistant", "content": "Hello from ollama"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 3,
            "eval_count": 2,
        },
    )


async def test_complete_maps_response() -> None:
    client = _make_client(_ok_handler)
    response = await client.complete(_request(ChatMessage(role=Role.user, content="hi")))
    assert response.content == "Hello from ollama"
    assert response.finish_reason == "stop"
    assert response.usage.prompt_tokens == 3
    assert response.usage.completion_tokens == 2
    assert response.usage.total_tokens == 5


async def test_astream_yields_deltas_and_final() -> None:
    client = _make_client(_ok_handler)
    chunks = [c async for c in client.astream(_request(ChatMessage(role=Role.user, content="hi")))]
    assert "".join(c.delta for c in chunks) == "hello"
    assert chunks[-1].done is True
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 5


async def test_tool_call_maps_tool_calls() -> None:
    client = _make_client(_ok_handler)
    tools = [ToolDefinition(name="lookup_order", description="d", parameters={"type": "object"})]
    response = await client.tool_call(_request(ChatMessage(role=Role.user, content="where")), tools)
    assert response.tool_calls == [
        ToolCall(id="lookup_order", name="lookup_order", arguments={"order_id": "1"})
    ]


async def test_structured_fails_loudly() -> None:
    client = _make_client(_ok_handler)

    class _S(BaseModel):
        a: int

    assert not client.supports(LLMCapability.structured)
    with pytest.raises(LLMCapabilityError):
        await client.structured(_request(ChatMessage(role=Role.user, content="q")), _S)


def _auth_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(401, json={"error": "unauthorized"})


async def test_http_error_is_normalized() -> None:
    client = _make_client(_auth_handler)
    with pytest.raises(LLMAuthError):
        await client.complete(_request(ChatMessage(role=Role.user, content="hi")))


async def test_error_details_are_safe() -> None:
    client = _make_client(_auth_handler)
    with pytest.raises(LLMAuthError) as excinfo:
        await client.complete(_request(ChatMessage(role=Role.user, content="hi")))
    assert excinfo.value.details["provider"] == "ollama"
    assert excinfo.value.retryable is False


async def test_payload_includes_options_and_model() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return _ok_handler(request)

    client = _make_client(handler)
    await client.complete(
        _request(ChatMessage(role=Role.user, content="hi"), temperature=0.7, max_tokens=32)
    )
    assert seen["model"] == "llama3"
    assert seen["options"]["temperature"] == pytest.approx(0.7)
    assert seen["options"]["num_predict"] == 32
    assert seen["stream"] is False


async def test_aclose_closes_client() -> None:
    transport = httpx.MockTransport(_ok_handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://ollama")
    client = OllamaLLMClient(model="llama3", client=http)
    await client.aclose()
    assert http.is_closed


def test_requires_model() -> None:
    with pytest.raises(ConfigurationError):
        OllamaLLMClient(model="")
