"""Provider adapter tests. All HTTP is mocked with ``httpx.MockTransport``."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from nexapilot.providers.anthropic import AnthropicProvider
from nexapilot.providers.base import ChatMessage, ChatRequest
from nexapilot.providers.gemini import GeminiProvider
from nexapilot.providers.ollama import OllamaProvider
from nexapilot.providers.openai import OpenAIProvider
from nexapilot.providers.registry import build_provider, list_provider_specs


def _sse_lines(payloads: list[dict[str, Any]]) -> bytes:
    body = ""
    for payload in payloads:
        body += f"data: {json.dumps(payload)}\n\n"
    return body.encode()


async def _collect(provider: Any, request: ChatRequest) -> list[Any]:
    return [event async for event in provider.stream(request)]


def _request() -> ChatRequest:
    return ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hello")],
    )


async def test_openai_streams_text_and_tool_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test"
        body = _sse_lines(
            [
                {
                    "choices": [
                        {
                            "delta": {"content": "Hi"},
                            "finish_reason": None,
                        }
                    ]
                },
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "web_search",
                                            "arguments": '{"q":"nexa"}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            ]
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = OpenAIProvider(
        api_key="sk-test", model="gpt-test", transport=httpx.MockTransport(handler)
    )
    events = await _collect(provider, _request())

    text = "".join(e.text for e in events if e.type == "text")
    tool_events = [e for e in events if e.type == "tool_call"]
    assert text == "Hi"
    assert len(tool_events) == 1
    assert tool_events[0].tool_call is not None
    assert tool_events[0].tool_call.name == "web_search"
    assert tool_events[0].tool_call.arguments == {"q": "nexa"}


async def test_openai_surfaces_auth_error_without_fallback() -> None:
    """A bad key must fail loudly — never silently fall back to another provider."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    provider = OpenAIProvider(
        api_key="sk-bad", model="gpt-test", transport=httpx.MockTransport(handler)
    )
    from nexapilot.core.errors import ProviderAuthError

    with pytest.raises(ProviderAuthError) as excinfo:
        await _collect(provider, _request())
    assert excinfo.value.http_status == 401


async def test_anthropic_parses_content_blocks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _sse_lines(
            [
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "Bonjour"},
                },
                {
                    "type": "message_stop",
                    "usage": {"input_tokens": 12, "output_tokens": 4},
                },
            ]
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = AnthropicProvider(
        api_key="sk-ant", model="claude-test", transport=httpx.MockTransport(handler)
    )
    events = await _collect(provider, _request())
    text = "".join(e.text for e in events if e.type == "text")
    assert text == "Bonjour"


async def test_ollama_native_api_streams_without_cloud_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.dumps(
            {
                "message": {"role": "assistant", "content": "Local reply"},
                "done": True,
                "prompt_eval_count": 5,
                "eval_count": 3,
            }
        )
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434", model="llama3", transport=httpx.MockTransport(handler)
    )
    events = await _collect(provider, _request())
    text = "".join(e.text for e in events if e.type == "text")
    assert text == "Local reply"


async def test_ollama_defaults_to_localhost_and_needs_no_key() -> None:
    provider = OllamaProvider(base_url="", model="llama3")
    assert provider.base_url == "http://127.0.0.1:11434"
    assert provider.requires_api_key is False


async def test_ollama_reports_unreachable_local_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434", model="llama3", transport=httpx.MockTransport(handler)
    )
    from nexapilot.core.errors import ProviderError

    with pytest.raises(ProviderError):
        await _collect(provider, _request())


async def test_gemini_streams_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _sse_lines(
            [
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "Ciao"}]}, "finishReason": "STOP"}
                    ],
                    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
                }
            ]
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    provider = GeminiProvider(
        api_key="gem-key", model="gemini-test", transport=httpx.MockTransport(handler)
    )
    events = await _collect(provider, _request())
    text = "".join(e.text for e in events if e.type == "text")
    assert text == "Ciao"


def test_registry_exposes_expected_providers() -> None:
    specs = {spec.id for spec in list_provider_specs()}
    assert {"openai", "anthropic", "ollama", "gemini", "custom"} <= specs


def test_registry_builds_provider_without_network() -> None:
    provider = build_provider("openai", api_key="sk-test", model="gpt-test")
    assert provider.provider_id == "openai"
    assert provider.model == "gpt-test"


def test_registry_rejects_unknown_provider() -> None:
    from nexapilot.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError):
        build_provider("does-not-exist", api_key="x", model="m")
