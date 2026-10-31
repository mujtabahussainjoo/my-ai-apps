"""OpenAI adapter.

Also serves OpenAI-compatible custom endpoints (vLLM, LM Studio, Groq, Together,
Ollama's ``/v1`` surface) through :class:`OpenAICompatibleProvider`.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexapilot.core.errors import ProviderError
from nexapilot.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ConnectionTestResult,
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


class OpenAIProvider(Provider):
    """Adapter for the OpenAI Chat Completions API."""

    provider_id = "openai"
    display_name = "OpenAI"
    default_base_url = "https://api.openai.com/v1"
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
            structured_output=True,
            system_prompt=True,
            vision=True,
            max_context_tokens=128_000,
        )

    # -- payload translation -------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers

    def _tool_payload(self, tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }

    def _messages_payload(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                payload.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id or message.name or "",
                        "content": message.content,
                    }
                )
                continue
            item: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, separators=(",", ":")),
                        },
                    }
                    for call in message.tool_calls
                ]
            payload.append(item)
        return payload

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": self._messages_payload(request.messages),
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.tools:
            payload["tools"] = [self._tool_payload(tool) for tool in request.tools]
            if request.tool_choice:
                payload["tool_choice"] = request.tool_choice
        if request.response_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_schema.get("title", "response"),
                    "schema": request.response_schema,
                    "strict": False,
                },
            }
        if request.stop:
            payload["stop"] = request.stop
        return payload

    # -- calls ---------------------------------------------------------------

    async def generate(self, request: ChatRequest) -> ChatResponse:
        timeout = request.timeout_seconds or self._timeout
        headers = self._headers()
        url = f"{self.base_url}/chat/completions"
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
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(
                f"{self.display_name} returned no choices", details={"provider": self.provider_id}
            )
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") or {}
        text = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") or {}
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed = {"__raw__": arguments}
            elif isinstance(arguments, dict):
                parsed = arguments
            else:
                parsed = {}
            tool_calls.append(
                ToolCall(
                    id=str(raw.get("id") or ""),
                    name=str(function.get("name") or ""),
                    arguments=parsed if isinstance(parsed, dict) else {},
                )
            )
        usage_raw = data.get("usage") or {}
        usage = TokenUsage(
            input_tokens=usage_raw.get("prompt_tokens"),
            output_tokens=usage_raw.get("completion_tokens"),
            total_tokens=usage_raw.get("total_tokens"),
        )
        finish = choice.get("finish_reason") or "stop"
        finish_reason = (
            "tool_calls" if finish == "tool_calls" else ("stop" if finish == "stop" else "length")
        )
        return ChatResponse(
            text=text if isinstance(text, str) else "",
            tool_calls=tool_calls,
            finish_reason=finish_reason,  # type: ignore[arg-type]
            usage=usage,
            provider=self.provider_id,
            model=str(data.get("model") or self.model),
            request_id=data.get("id"),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        timeout = request.timeout_seconds or self._timeout
        headers = self._headers()
        url = f"{self.base_url}/chat/completions"
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
        tool_accumulator: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        async for chunk in sse_json(response):
            if "error" in chunk and isinstance(chunk["error"], dict):
                raise ProviderError(
                    f"{self.display_name} stream error",
                    details={"provider": self.provider_id},
                )
            choices = chunk.get("choices") or []
            if not choices or not isinstance(choices[0], dict):
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str) and content:
                yield StreamEvent(type="text", text=content)
            for raw in delta.get("tool_calls") or []:
                if not isinstance(raw, dict):
                    continue
                index = int(raw.get("index") or 0)
                entry = tool_accumulator.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if raw.get("id"):
                    entry["id"] = str(raw["id"])
                function = raw.get("function") or {}
                if function.get("name"):
                    entry["name"] = str(function["name"])
                if isinstance(function.get("arguments"), str):
                    entry["arguments"] += function["arguments"]
            if choice.get("finish_reason"):
                raw_finish = str(choice["finish_reason"])
                finish_reason = "tool_calls" if raw_finish == "tool_calls" else raw_finish

        for index in sorted(tool_accumulator):
            entry = tool_accumulator[index]
            try:
                arguments = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                arguments = {"__raw__": entry["arguments"]}
            yield StreamEvent(
                type="tool_call",
                tool_call=ToolCall(
                    id=entry["id"],
                    name=entry["name"],
                    arguments=arguments if isinstance(arguments, dict) else {},
                ),
            )
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


class OpenAICompatibleProvider(OpenAIProvider):
    """OpenAI-compatible custom endpoint (vLLM, LM Studio, Groq, Together, ...)."""

    provider_id = "custom"
    display_name = "Custom OpenAI-compatible endpoint"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            tool_calling=True,
            structured_output=False,
            system_prompt=True,
            vision=False,
            max_context_tokens=32_000,
        )

    async def test_connection(self) -> ConnectionTestResult:
        """A custom endpoint may be local and offline; report reachability first."""
        import time

        started = time.perf_counter()
        try:
            models = await self.list_models()
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            return ConnectionTestResult(
                ok=False,
                provider=self.provider_id,
                model=self.model,
                message=f"endpoint unreachable: {exc}",
                latency_ms=latency,
                capabilities=self.capabilities,
                error_code="provider_unreachable",
            )
        latency = int((time.perf_counter() - started) * 1000)
        if models and self.model not in models:
            return ConnectionTestResult(
                ok=True,
                provider=self.provider_id,
                model=self.model,
                message=(
                    f"endpoint reachable; model '{self.model}' was not listed "
                    f"({len(models)} models available)"
                ),
                latency_ms=latency,
                capabilities=self.capabilities,
            )
        return ConnectionTestResult(
            ok=True,
            provider=self.provider_id,
            model=self.model,
            message="endpoint reachable",
            latency_ms=latency,
            capabilities=self.capabilities,
        )
