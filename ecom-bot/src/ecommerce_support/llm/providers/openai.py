"""OpenAI Chat Completions provider adapter (INT-001, NFR-007).

The only module that talks to the OpenAI SDK. It translates provider-neutral contracts to/from
the Chat Completions API and normalizes SDK errors at the boundary. ``max_retries=0`` so our
layer owns retry policy (TASK-015).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai.types.completion_usage import CompletionUsage

from ecommerce_support.core.exceptions import ConfigurationError, LLMError
from ecommerce_support.llm.base import LLMClient, ModelT
from ecommerce_support.llm.capabilities import LLMCapability, capabilities_for
from ecommerce_support.llm.errors import normalize_error
from ecommerce_support.llm.types import (
    CompletionRequest,
    CompletionResponse,
    JSONDict,
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


def _to_openai_messages(request: CompletionRequest) -> list[dict[str, Any]]:
    system = _extract_system(request)
    messages: list[dict[str, Any]] = []
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
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
        else:
            messages.append({"role": message.role.value, "content": message.content})
    return messages


def _to_openai_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _to_openai_tool_choice(tool_choice: str | None) -> str | dict[str, Any] | None:
    if tool_choice is None or tool_choice == "auto":
        return "auto"
    if tool_choice in {"any", "required"}:
        return "required"
    if tool_choice == "none":
        return "none"
    return {"type": "function", "function": {"name": tool_choice}}


def _to_usage(usage: CompletionUsage | None) -> Usage | None:
    if usage is None:
        return None
    return Usage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _arguments_to_json(raw: str | None) -> JSONDict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": parsed}


def _message_to_tool_calls(message: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for tool_call in getattr(message, "tool_calls", None) or []:
        function = tool_call.function
        calls.append(
            ToolCall(
                id=tool_call.id,
                name=function.name,
                arguments=_arguments_to_json(function.arguments),
            )
        )
    return calls


def _completion_to_response(completion: ChatCompletion) -> CompletionResponse:
    choice = completion.choices[0]
    message = choice.message
    return CompletionResponse(
        content=message.content or "",
        model=completion.model,
        finish_reason=choice.finish_reason,
        usage=_to_usage(completion.usage) or Usage(),
        tool_calls=_message_to_tool_calls(message),
    )


class OpenAILLMClient(LLMClient):
    """OpenAI Chat Completions implementation of :class:`LLMClient`."""

    provider = "openai"
    capabilities = capabilities_for("openai")

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if not model:
            raise ConfigurationError("OpenAI provider requires a model name.")
        if client is None:
            if not api_key:
                raise ConfigurationError(
                    "OpenAI provider requires an API key (set LLM__OPENAI_API_KEY)."
                )
            client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def model_name(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.require(LLMCapability.complete)
        try:
            completion = await self._client.chat.completions.create(**self._build_kwargs(request))
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        return _completion_to_response(self._ensure_completion(completion))

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        self.require(LLMCapability.stream)
        kwargs = self._build_kwargs(request)
        finish_reason: str | None = None
        usage: Usage | None = None
        try:
            kwargs["stream"] = True
            kwargs["include_usage"] = True
            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                assert isinstance(chunk, ChatCompletionChunk)
                if chunk.choices:
                    choice = chunk.choices[0]
                    piece = choice.delta.content or ""
                    if piece:
                        yield StreamChunk(delta=piece)
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                if chunk.usage:
                    usage = _to_usage(chunk.usage)
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        yield StreamChunk(done=True, finish_reason=finish_reason or "stop", usage=usage)

    async def structured(
        self,
        request: CompletionRequest,
        schema: type[ModelT],
    ) -> ModelT:
        self.require(LLMCapability.structured)
        kwargs = self._build_kwargs(request)
        try:
            completion = await self._client.chat.completions.parse(**kwargs, response_format=schema)
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise LLMError(
                "OpenAI did not return structured output.",
                details={"provider": self.provider, "schema": schema.__name__},
            )
        return parsed

    async def tool_call(
        self,
        request: CompletionRequest,
        tools: Sequence[ToolDefinition],
        *,
        tool_choice: str | None = None,
    ) -> CompletionResponse:
        self.require(LLMCapability.tool_calling)
        kwargs = self._build_kwargs(request)
        if tools:
            kwargs["tools"] = [_to_openai_tool(tool) for tool in tools]
            kwargs["tool_choice"] = _to_openai_tool_choice(tool_choice)
        try:
            completion = await self._client.chat.completions.create(**kwargs)
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        return _completion_to_response(self._ensure_completion(completion))

    async def aclose(self) -> None:
        await self._client.close()

    # -- internals ---------------------------------------------------------

    def _build_kwargs(self, request: CompletionRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model or self._model,
            "messages": _to_openai_messages(request),
        }
        max_tokens = request.max_tokens or self._max_tokens
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        temperature = request.temperature if request.temperature is not None else self._temperature
        if temperature is not None:
            kwargs["temperature"] = temperature
        if request.stop:
            kwargs["stop"] = list(request.stop)
        return kwargs

    @staticmethod
    def _ensure_completion(completion: ChatCompletion | object) -> ChatCompletion:
        if not isinstance(completion, ChatCompletion):
            raise LLMError(
                "Expected a non-streaming OpenAI ChatCompletion response.",
                details={"provider": "openai"},
            )
        return completion
