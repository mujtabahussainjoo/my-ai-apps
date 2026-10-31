"""Google Gemini adapter (generateContent / streamGenerateContent)."""

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
    sse_json,
    wrap_transport_error,
)


class GeminiProvider(Provider):
    provider_id = "gemini"
    display_name = "Google Gemini"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"
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
            max_context_tokens=1_000_000,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key
        return headers

    def _tool_payload(self, tool: ToolDefinition) -> dict[str, Any]:
        parameters = tool.parameters or {"type": "object", "properties": {}}
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        }

    def _split_messages(self, messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                if message.content:
                    system_parts.append(message.content)
                continue
            if message.role == "tool":
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": message.name or message.tool_call_id or "tool",
                                    "response": {"result": message.content},
                                }
                            }
                        ],
                    }
                )
                continue
            parts: list[dict[str, Any]] = []
            if message.content:
                parts.append({"text": message.content})
            for call in message.tool_calls:
                parts.append({"functionCall": {"name": call.name, "args": call.arguments}})
            if parts:
                role = "model" if message.role == "assistant" else "user"
                contents.append({"role": role, "parts": parts})
        return "\n\n".join(system_parts), contents

    def _build_payload(self, request: ChatRequest) -> dict[str, Any]:
        system, contents = self._split_messages(request.messages)
        payload: dict[str, Any] = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        generation: dict[str, Any] = {}
        if request.temperature is not None:
            generation["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            generation["maxOutputTokens"] = request.max_output_tokens
        if request.stop:
            generation["stopSequences"] = request.stop
        if request.response_schema:
            generation["responseMimeType"] = "application/json"
            generation["responseSchema"] = request.response_schema
        if generation:
            payload["generationConfig"] = generation
        if request.tools:
            payload["tools"] = [
                {"functionDeclarations": [self._tool_payload(t) for t in request.tools]}
            ]
        return payload

    async def generate(self, request: ChatRequest) -> ChatResponse:
        timeout = request.timeout_seconds or self._timeout
        headers = self._headers()
        model = request.model or self.model
        url = f"{self.base_url}/models/{model}:generateContent"
        async with build_client(
            timeout=timeout, headers=headers, transport=self._transport
        ) as client:
            try:
                response = await client.post(
                    url, json=self._build_payload(request), headers=headers
                )
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, self.display_name, timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, self.display_name, response.text)
            data = response.json()
        return self._parse_response(data, model)

    def _parse_response(self, data: dict[str, Any], model: str) -> ChatResponse:
        candidates = data.get("candidates") or []
        if not candidates or not isinstance(candidates[0], dict):
            raise ProviderError(
                f"{self.display_name} returned no candidates",
                details={"provider": self.provider_id},
            )
        candidate = candidates[0]
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if isinstance(part.get("text"), str):
                text_parts.append(part["text"])
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                arguments = function_call.get("args")
                tool_calls.append(
                    ToolCall(
                        id=str(function_call.get("id") or function_call.get("name") or ""),
                        name=str(function_call.get("name") or ""),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
        finish_reason = "tool_calls" if tool_calls else "stop"
        raw_finish = candidate.get("finishReason")
        if raw_finish == "MAX_TOKENS":
            finish_reason = "length"
        usage_raw = data.get("usageMetadata") or {}
        return ChatResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,  # type: ignore[arg-type]
            usage=TokenUsage(
                input_tokens=usage_raw.get("promptTokenCount"),
                output_tokens=usage_raw.get("candidatesTokenCount"),
                total_tokens=usage_raw.get("totalTokenCount"),
            ),
            provider=self.provider_id,
            model=model,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        timeout = request.timeout_seconds or self._timeout
        headers = self._headers()
        model = request.model or self.model
        url = f"{self.base_url}/models/{model}:streamGenerateContent?alt=sse"
        async with build_client(
            timeout=timeout, headers=headers, transport=self._transport
        ) as client:
            try:
                async with client.stream(
                    "POST", url, json=self._build_payload(request), headers=headers
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise classify_status(response.status_code, self.display_name, body)
                    async for event in self._consume_stream(response, model):
                        yield event
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, self.display_name, timeout) from exc

    async def _consume_stream(
        self, response: httpx.Response, model: str
    ) -> AsyncIterator[StreamEvent]:
        tool_index = 0
        usage = TokenUsage()
        async for chunk in sse_json(response):
            candidates = chunk.get("candidates") or []
            if not candidates or not isinstance(candidates[0], dict):
                usage_raw = chunk.get("usageMetadata") or {}
                if usage_raw:
                    usage = TokenUsage(
                        input_tokens=usage_raw.get("promptTokenCount"),
                        output_tokens=usage_raw.get("candidatesTokenCount"),
                        total_tokens=usage_raw.get("totalTokenCount"),
                    )
                continue
            candidate = candidates[0]
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                if isinstance(part.get("text"), str) and part["text"]:
                    yield StreamEvent(type="text", text=part["text"])
                function_call = part.get("functionCall")
                if isinstance(function_call, dict):
                    arguments = function_call.get("args")
                    tool_index += 1
                    yield StreamEvent(
                        type="tool_call",
                        tool_call=ToolCall(
                            id=str(function_call.get("id") or f"call_{tool_index}"),
                            name=str(function_call.get("name") or ""),
                            arguments=arguments if isinstance(arguments, dict) else {},
                        ),
                    )
        yield StreamEvent(type="usage", usage=usage)
        yield StreamEvent(type="done", finish_reason="stop")

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
        models = [
            item.get("name")
            for item in data.get("models", [])
            if isinstance(item, dict)
            and "generateContent" in (item.get("supportedGenerationMethods") or [])
        ]
        return sorted(str(model).replace("models/", "") for model in models if model)
