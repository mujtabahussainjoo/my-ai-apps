"""Anthropic Claude adapter (Messages API)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexapilot.core.errors import ProviderError
from nexapilot.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    Provider,
    ProviderCapabilities,
    StreamEvent,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from nexapilot.providers.http import (
    build_client,
    classify_status,
    post_json,
    sse_json,
    wrap_transport_error,
)

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(Provider):
    provider_id = "anthropic"
    display_name = "Anthropic Claude"
    default_base_url = "https://api.anthropic.com/v1"
    requires_api_key = True

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "",
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(model=model, base_url=base_url or self.default_base_url, api_key=api_key)
        self._transport = transport
        self._timeout = timeout

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=False,
            system_prompt=True,
            vision=True,
            max_context_tokens=200_000,
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    def _split_messages(self, messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
        """Anthropic takes the system prompt out of band."""
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                if message.content:
                    system_parts.append(message.content)
                continue
            if message.role == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id or message.name or "",
                                "content": message.content,
                            }
                        ],
                    }
                )
                continue
            if message.tool_calls:
                blocks: list[dict[str, Any]] = []
                if message.content:
                    blocks.append({"type": "text", "text": message.content})
                for call in message.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call.id or call.name,
                            "name": call.name,
                            "input": call.arguments,
                        }
                    )
                converted.append({"role": "assistant", "content": blocks})
                continue
            converted.append({"role": message.role, "content": message.content})
        return "\n\n".join(system_parts), converted

    def _tool_payload(self, tool: ToolDefinition) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
        }

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        system, messages = self._split_messages(request.messages)
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens or 4096,
        }
        if system:
            payload["system"] = system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = [self._tool_payload(tool) for tool in request.tools]
        if request.stop:
            payload["stop_sequences"] = request.stop
        return payload

    async def generate(self, request: ChatRequest) -> ChatResponse:
        timeout = request.timeout_seconds or self._timeout
        headers = self._headers()
        url = f"{self.base_url}/messages"
        async with build_client(
            timeout=timeout, headers=headers, transport=self._transport
        ) as client:
            data = await post_json(
                client,
                url,
                payload=self._build_payload(request, stream=False),
                provider=self.display_name,
                timeout=timeout,
            )
        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> ChatResponse:
        content = data.get("content")
        if not isinstance(content, list):
            raise ProviderError(
                f"{self.display_name} returned an unexpected content payload",
                details={"provider": self.provider_id},
            )
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(str(block.get("text") or ""))
            elif block_type == "tool_use":
                arguments = block.get("input")
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
        stop_reason = data.get("stop_reason")
        finish_reason = (
            "tool_calls"
            if stop_reason == "tool_use"
            else ("length" if stop_reason == "max_tokens" else "stop")
        )
        usage_raw = data.get("usage") or {}
        return ChatResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,  # type: ignore[arg-type]
            usage=TokenUsage(
                input_tokens=usage_raw.get("input_tokens"),
                output_tokens=usage_raw.get("output_tokens"),
                total_tokens=(usage_raw.get("input_tokens") or 0)
                + (usage_raw.get("output_tokens") or 0)
                or None,
            ),
            provider=self.provider_id,
            model=str(data.get("model") or self.model),
            request_id=data.get("id"),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        timeout = request.timeout_seconds or self._timeout
        headers = self._headers()
        url = f"{self.base_url}/messages"
        async with build_client(
            timeout=timeout, headers=headers, transport=self._transport
        ) as client:
            try:
                async with client.stream(
                    "POST",
                    url,
                    json=self._build_payload(request, stream=True),
                    headers=headers,
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise classify_status(response.status_code, self.display_name, body)
                    async for event in self._consume_stream(response):
                        yield event
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, self.display_name, timeout) from exc

    async def _consume_stream(self, response: httpx.Response) -> AsyncIterator[StreamEvent]:
        finish_reason = "stop"
        usage = TokenUsage()
        async for chunk in sse_json(response):
            event_type = chunk.get("type")
            if event_type == "content_block_start":
                block = chunk.get("content_block") or {}
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield StreamEvent(
                        type="tool_call",
                        tool_call=ToolCall(
                            id=str(block.get("id") or ""),
                            name=str(block.get("name") or ""),
                            arguments={},
                        ),
                    )
                continue
            if event_type == "content_block_delta":
                delta = chunk.get("delta") or {}
                delta_type = delta.get("type")
                if delta_type == "text_delta":
                    yield StreamEvent(type="text", text=str(delta.get("text") or ""))
                continue
            if event_type == "message_delta":
                delta = chunk.get("delta") or {}
                if delta.get("stop_reason"):
                    raw = str(delta["stop_reason"])
                    finish_reason = "tool_calls" if raw == "tool_use" else raw
                usage_raw = chunk.get("usage") or {}
                if usage_raw.get("output_tokens") is not None:
                    usage.output_tokens = usage_raw.get("output_tokens")
                continue
            if event_type == "message_start":
                message = chunk.get("message") or {}
                usage_raw = message.get("usage") or {}
                if usage_raw.get("input_tokens") is not None:
                    usage.input_tokens = usage_raw.get("input_tokens")
                continue
        yield StreamEvent(type="usage", usage=usage)
        yield StreamEvent(type="done", finish_reason=finish_reason)  # type: ignore[arg-type]

    async def list_models(self) -> list[str]:
        timeout = self._timeout
        headers = self._headers()
        async with build_client(
            timeout=timeout, headers=headers, transport=self._transport
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/models", headers=headers)
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, self.display_name, timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, self.display_name, response.text)
            data = response.json()
        models = [item.get("id") for item in data.get("data", []) if isinstance(item, dict)]
        return sorted(str(model) for model in models if model)
