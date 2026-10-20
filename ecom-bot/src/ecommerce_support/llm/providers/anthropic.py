"""Anthropic Claude provider adapter (INT-001, NFR-007).

The only module that talks to the Anthropic SDK. It translates provider-neutral contracts in
:mod:`ecommerce_support.llm.types` to/from Anthropic's Messages API. Provider SDK errors are
normalized to the app's :mod:`ecommerce_support.core.exceptions` hierarchy at the boundary.

Retry/backoff policy is enforced by our layer, not the SDK (``max_retries=0``); timeout and
retry tuning live in the LLM layer (NFR-003, TASK-015).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message, TextBlock, ToolUseBlock

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

_STRUCTURED_TOOL_NAME = "emit_structured_output"


def _extract_system(request: CompletionRequest) -> str | None:
    parts: list[str] = []
    if request.system:
        parts.append(request.system)
    parts.extend(m.content for m in request.messages if m.role is Role.system)
    return "\n\n".join(p for p in parts if p) or None


def _to_anthropic_messages(request: CompletionRequest) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role is Role.system:
            continue
        if message.role is Role.tool:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id or "",
                            "content": message.content,
                        }
                    ],
                }
            )
        elif message.role is Role.assistant and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                for call in message.tool_calls
            )
            messages.append({"role": "assistant", "content": blocks})
        else:
            messages.append({"role": message.role.value, "content": message.content})
    return messages


def _to_anthropic_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
    }


def _to_anthropic_tool_choice(tool_choice: str | None) -> dict[str, Any] | None:
    if tool_choice is None or tool_choice == "auto":
        return None
    if tool_choice in {"any", "required"}:
        return {"type": "any"}
    if tool_choice == "none":
        return {"type": "none"}
    return {"type": "tool", "name": tool_choice}


def _to_completion_response(message: Message) -> CompletionResponse:
    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            texts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            arguments: JSONDict = dict(block.input) if isinstance(block.input, dict) else {}
            tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=arguments))
    prompt_tokens = message.usage.input_tokens
    completion_tokens = message.usage.output_tokens
    return CompletionResponse(
        content="".join(texts),
        model=message.model,
        finish_reason=message.stop_reason or "stop",
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        tool_calls=tool_calls,
    )


def _normalize(error: Exception) -> LLMError:
    return normalize_error("anthropic", error)


class AnthropicLLMClient(LLMClient):
    """Anthropic Claude implementation of :class:`LLMClient`."""

    provider = "anthropic"
    capabilities = capabilities_for("anthropic")

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        client: AsyncAnthropic | None = None,
    ) -> None:
        if not model:
            raise ConfigurationError("Anthropic provider requires a model name.")
        if client is None:
            if not api_key:
                raise ConfigurationError(
                    "Anthropic provider requires an API key (set LLM__ANTHROPIC_API_KEY)."
                )
            client = AsyncAnthropic(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=0,
            )
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def model_name(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.require(LLMCapability.complete)
        try:
            message = await self._client.messages.create(**self._build_kwargs(request))
        except Exception as error:
            raise _normalize(error) from error
        return _to_completion_response(self._ensure_message(message))

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        self.require(LLMCapability.stream)
        kwargs = self._build_kwargs(request)
        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield StreamChunk(delta=text)
                final = await stream.get_final_message()
        except Exception as error:
            raise _normalize(error) from error
        yield StreamChunk(
            done=True,
            finish_reason=final.stop_reason or "stop",
            usage=Usage(
                prompt_tokens=final.usage.input_tokens,
                completion_tokens=final.usage.output_tokens,
                total_tokens=final.usage.input_tokens + final.usage.output_tokens,
            ),
        )

    async def structured(
        self,
        request: CompletionRequest,
        schema: type[ModelT],
    ) -> ModelT:
        self.require(LLMCapability.structured)
        kwargs = self._build_kwargs(request)
        kwargs["tools"] = [
            {
                "name": _STRUCTURED_TOOL_NAME,
                "description": "Return the answer as structured JSON matching the schema.",
                "input_schema": schema.model_json_schema(),
            }
        ]
        kwargs["tool_choice"] = {"type": "tool", "name": _STRUCTURED_TOOL_NAME}
        try:
            message = await self._client.messages.create(**kwargs)
        except Exception as error:
            raise _normalize(error) from error
        for block in self._ensure_message(message).content:
            if (
                isinstance(block, ToolUseBlock)
                and block.name == _STRUCTURED_TOOL_NAME
                and isinstance(block.input, dict)
            ):
                return schema.model_validate(block.input)
        raise LLMError(
            "Anthropic did not return structured output.",
            details={"provider": "anthropic", "schema": schema.__name__},
        )

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
            kwargs["tools"] = [_to_anthropic_tool(tool) for tool in tools]
            choice = _to_anthropic_tool_choice(tool_choice)
            if choice is not None:
                kwargs["tool_choice"] = choice
        try:
            message = await self._client.messages.create(**kwargs)
        except Exception as error:
            raise _normalize(error) from error
        return _to_completion_response(self._ensure_message(message))

    async def aclose(self) -> None:
        await self._client.close()

    # -- internals ---------------------------------------------------------

    def _build_kwargs(self, request: CompletionRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model or self._model,
            "max_tokens": request.max_tokens or self._max_tokens,
            "messages": _to_anthropic_messages(request),
        }
        system = _extract_system(request)
        if system is not None:
            kwargs["system"] = system
        temperature = request.temperature if request.temperature is not None else self._temperature
        if temperature is not None:
            kwargs["temperature"] = temperature
        if request.stop:
            kwargs["stop_sequences"] = list(request.stop)
        return kwargs

    @staticmethod
    def _ensure_message(message: Message | object) -> Message:
        if not isinstance(message, Message):
            raise LLMError(
                "Expected a non-streaming Anthropic Message response.",
                details={"provider": "anthropic"},
            )
        return message
