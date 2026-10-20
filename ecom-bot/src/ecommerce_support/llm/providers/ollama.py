"""Ollama provider adapter over its HTTP API (INT-001, NFR-007).

Ollama has no bundled Python SDK in this project, so we call its ``/api/chat`` endpoint with
``httpx`` (injectable for offline tests). Structured output is intentionally not declared in the
capability matrix (support is model-dependent), so requesting it fails loudly with
``LLMCapabilityError``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from ecommerce_support.core.exceptions import ConfigurationError, LLMError
from ecommerce_support.llm.base import LLMClient, ModelT
from ecommerce_support.llm.capabilities import LLMCapability, capabilities_for
from ecommerce_support.llm.errors import normalize_error
from ecommerce_support.llm.types import (
    CompletionRequest,
    CompletionResponse,
    Role,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    Usage,
)


def _extract_system(request: CompletionRequest) -> str | None:
    parts: list[str] = []
    if request.system:
        parts.append(request.system)
    parts.extend(m.content for m in request.messages if m.role is Role.system)
    return "\n\n".join(p for p in parts if p) or None


def _to_ollama_messages(request: CompletionRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system = _extract_system(request)
    if system is not None:
        messages.append({"role": "system", "content": system})
    for message in request.messages:
        if message.role is Role.system:
            continue
        if message.role is Role.tool:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id or "",
                    "content": message.content,
                }
            )
        elif message.role is Role.assistant and message.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {"function": {"name": call.name, "arguments": call.arguments}}
                        for call in message.tool_calls
                    ],
                }
            )
        else:
            messages.append({"role": message.role.value, "content": message.content})
    return messages


def _to_ollama_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _usage_from(data: dict[str, Any]) -> Usage:
    prompt = int(data.get("prompt_eval_count") or 0)
    completion = int(data.get("eval_count") or 0)
    return Usage(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def _tool_calls_from(message: dict[str, Any]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function", {})
        arguments = function.get("arguments", {})
        calls.append(
            ToolCall(
                id=str(tool_call.get("id") or function.get("name") or ""),
                name=function.get("name", ""),
                arguments=arguments if isinstance(arguments, dict) else {"_raw": arguments},
            )
        )
    return calls


class OllamaLLMClient(LLMClient):
    """Ollama implementation of :class:`LLMClient` over ``/api/chat``."""

    provider = "ollama"
    capabilities = capabilities_for("ollama")

    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not model:
            raise ConfigurationError("Ollama provider requires a model name.")
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def model_name(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.require(LLMCapability.complete)
        try:
            response = await self._client.post(
                "/api/chat", json=self._build_payload(request, False)
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        return self._to_response(data)

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        self.require(LLMCapability.stream)
        finish_reason: str | None = None
        usage: Usage | None = None
        try:
            async with self._client.stream(
                "POST", "/api/chat", json=self._build_payload(request, True)
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    obj: dict[str, Any] = json.loads(line)
                    message = obj.get("message", {})
                    piece = message.get("content") or ""
                    if piece:
                        yield StreamChunk(delta=piece)
                    if obj.get("done"):
                        finish_reason = obj.get("done_reason")
                        usage = _usage_from(obj)
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        yield StreamChunk(done=True, finish_reason=finish_reason or "stop", usage=usage)

    async def structured(
        self,
        request: CompletionRequest,
        schema: type[ModelT],
    ) -> ModelT:
        self.require(LLMCapability.structured)
        # Unreachable while the capability matrix omits ``structured`` for Ollama.
        raise LLMError(
            "Ollama structured output is not supported.",
            details={"provider": self.provider, "schema": schema.__name__},
        )

    async def tool_call(
        self,
        request: CompletionRequest,
        tools: Sequence[ToolDefinition],
        *,
        tool_choice: str | None = None,
    ) -> CompletionResponse:
        self.require(LLMCapability.tool_calling)
        payload = self._build_payload(request, False)
        if tools:
            payload["tools"] = [_to_ollama_tool(tool) for tool in tools]
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        return self._to_response(data)

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- internals ---------------------------------------------------------

    def _build_payload(self, request: CompletionRequest, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self._model,
            "messages": _to_ollama_messages(request),
            "stream": stream,
        }
        options: dict[str, Any] = {}
        temperature = request.temperature if request.temperature is not None else self._temperature
        if temperature is not None:
            options["temperature"] = temperature
        if request.max_tokens or self._max_tokens:
            options["num_predict"] = request.max_tokens or self._max_tokens
        if options:
            payload["options"] = options
        return payload

    @staticmethod
    def _to_response(data: dict[str, Any]) -> CompletionResponse:
        message = data.get("message", {})
        return CompletionResponse(
            content=message.get("content") or "",
            model=data.get("model", ""),
            finish_reason=data.get("done_reason") or "stop",
            usage=_usage_from(data),
            tool_calls=_tool_calls_from(message),
        )
