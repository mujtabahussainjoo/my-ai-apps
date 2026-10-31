"""Ollama adapter (native API).

Ollama runs locally; no cloud API key is required. The adapter talks to the
native ``/api/chat`` endpoint, which is stable across Ollama versions and does
not require the OpenAI compatibility layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexapilot.providers.base import (
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
    ndjson,
    post_json,
    wrap_transport_error,
)


class OllamaProvider(Provider):
    provider_id = "ollama"
    display_name = "Ollama (local)"
    default_base_url = "http://127.0.0.1:11434"
    requires_api_key = False

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "",
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 300.0,
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
            vision=False,
            max_context_tokens=32_000,
        )

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

    def _build_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            if message.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "content": message.content,
                        "tool_name": message.name or "",
                    }
                )
                continue
            item: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in message.tool_calls
                ]
            messages.append(item)

        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            options["num_predict"] = request.max_output_tokens
        if request.stop:
            options["stop"] = request.stop

        payload: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": messages,
            "stream": stream,
        }
        if options:
            payload["options"] = options
        if request.tools:
            payload["tools"] = [self._tool_payload(tool) for tool in request.tools]
        return payload

    async def generate(self, request: ChatRequest) -> ChatResponse:
        timeout = request.timeout_seconds or self._timeout
        headers = self._headers()
        url = f"{self.base_url}/api/chat"
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
        message = data.get("message") or {}
        text = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for index, raw in enumerate(message.get("tool_calls") or []):
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") or {}
            arguments = function.get("arguments")
            tool_calls.append(
                ToolCall(
                    id=str(raw.get("id") or f"call_{index}"),
                    name=str(function.get("name") or ""),
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        done_reason = data.get("done_reason") or "stop"
        finish_reason = (
            "tool_calls" if tool_calls else ("length" if done_reason == "length" else "stop")
        )
        prompt_tokens = data.get("prompt_eval_count")
        eval_tokens = data.get("eval_count")
        total = None
        if isinstance(prompt_tokens, int) and isinstance(eval_tokens, int):
            total = prompt_tokens + eval_tokens
        return ChatResponse(
            text=text if isinstance(text, str) else "",
            tool_calls=tool_calls,
            finish_reason=finish_reason,  # type: ignore[arg-type]
            usage=TokenUsage(
                input_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
                output_tokens=eval_tokens if isinstance(eval_tokens, int) else None,
                total_tokens=total,
            ),
            provider=self.provider_id,
            model=str(data.get("model") or self.model),
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        timeout = request.timeout_seconds or self._timeout
        headers = self._headers()
        url = f"{self.base_url}/api/chat"
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
        async for chunk in ndjson(response):
            message = chunk.get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content:
                yield StreamEvent(type="text", text=content)
            for index, raw in enumerate(message.get("tool_calls") or []):
                if not isinstance(raw, dict):
                    continue
                function = raw.get("function") or {}
                arguments = function.get("arguments")
                yield StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(
                        id=str(raw.get("id") or f"call_{index}"),
                        name=str(function.get("name") or ""),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    ),
                )
            if chunk.get("done"):
                done_reason = chunk.get("done_reason") or "stop"
                finish_reason = "length" if done_reason == "length" else "stop"
                prompt_tokens = chunk.get("prompt_eval_count")
                eval_tokens = chunk.get("eval_count")
                usage = TokenUsage(
                    input_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
                    output_tokens=eval_tokens if isinstance(eval_tokens, int) else None,
                )
        yield StreamEvent(type="usage", usage=usage)
        yield StreamEvent(type="done", finish_reason=finish_reason)  # type: ignore[arg-type]

    async def list_models(self) -> list[str]:
        timeout = min(self._timeout, 30.0)
        headers = self._headers()
        async with build_client(
            timeout=timeout, headers=headers, transport=self._transport
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/api/tags", headers=headers)
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, self.display_name, timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, self.display_name, response.text)
            data = response.json()
        models = [item.get("name") for item in data.get("models", []) if isinstance(item, dict)]
        return sorted(str(model) for model in models if model)

    async def test_connection(self) -> ConnectionTestResult:
        """Verify the local Ollama server is reachable and the model is pulled."""
        import time

        started = time.perf_counter()
        try:
            models = await self.list_models()
        except Exception:
            latency = int((time.perf_counter() - started) * 1000)
            return ConnectionTestResult(
                ok=False,
                provider=self.provider_id,
                model=self.model,
                message=(
                    "Ollama is not reachable. Install Ollama (https://ollama.com), start it, "
                    f"and run `ollama pull {self.model}`."
                ),
                latency_ms=latency,
                capabilities=self.capabilities,
                error_code="provider_unreachable",
            )
        latency = int((time.perf_counter() - started) * 1000)
        if models and self.model not in models:
            return ConnectionTestResult(
                ok=False,
                provider=self.provider_id,
                model=self.model,
                message=(
                    f"Ollama is running but model '{self.model}' is not installed. "
                    f"Run `ollama pull {self.model}`. Installed: {', '.join(models[:10])}"
                ),
                latency_ms=latency,
                capabilities=self.capabilities,
                error_code="model_not_installed",
            )
        return ConnectionTestResult(
            ok=True,
            provider=self.provider_id,
            model=self.model,
            message="Ollama reachable",
            latency_ms=latency,
            capabilities=self.capabilities,
        )
