"""Google Gemini provider adapter (INT-001, NFR-007).

The only module that talks to the ``google-genai`` SDK. It translates provider-neutral
contracts to/from the ``generate_content`` API and normalizes SDK errors at the boundary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from google import genai
from google.genai import types

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


def _tool_name_lookup(request: CompletionRequest) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for message in request.messages:
        for call in message.tool_calls:
            lookup[call.id] = call.name
    return lookup


def _to_contents(request: CompletionRequest) -> list[types.Content]:
    lookup = _tool_name_lookup(request)
    contents: list[types.Content] = []
    for message in request.messages:
        if message.role is Role.system:
            continue
        if message.role is Role.tool:
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=lookup.get(
                                    message.tool_call_id or "", message.tool_call_id or ""
                                ),
                                response={"result": message.content},
                            )
                        )
                    ],
                )
            )
        elif message.role is Role.assistant and message.tool_calls:
            parts: list[types.Part] = []
            if message.content:
                parts.append(types.Part(text=message.content))
            parts.extend(
                types.Part(
                    function_call=types.FunctionCall(
                        id=call.id, name=call.name, args=dict(call.arguments)
                    )
                )
                for call in message.tool_calls
            )
            contents.append(types.Content(role="model", parts=parts))
        else:
            contents.append(types.Content(role="user", parts=[types.Part(text=message.content)]))
    return contents


def _to_function_declarations(tools: Sequence[ToolDefinition]) -> list[types.FunctionDeclaration]:
    declarations: list[types.FunctionDeclaration] = []
    for tool in tools:
        declarations.append(
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters or None,
            )
        )
    return declarations


def _finish_reason(value: Any) -> str:
    name = getattr(value, "name", None)
    return (name or "STOP").lower()


def _usage_from(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
    completion = int(getattr(usage, "candidates_token_count", 0) or 0)
    total = int(getattr(usage, "total_token_count", 0) or (prompt + completion))
    return Usage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _parts_to_response(response: Any, model: str) -> CompletionResponse:
    candidates = getattr(response, "candidates", None) or []
    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    finish = "stop"
    if candidates:
        candidate = candidates[0]
        finish = _finish_reason(getattr(candidate, "finish_reason", None))
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            if part.text:
                texts.append(part.text)
            if part.function_call:
                call = part.function_call
                tool_calls.append(
                    ToolCall(
                        id=call.id or call.name,
                        name=call.name,
                        arguments=dict(call.args or {}),
                    )
                )
    return CompletionResponse(
        content="".join(texts),
        model=getattr(response, "model_version", None) or model,
        finish_reason=finish,
        usage=_usage_from(getattr(response, "usage_metadata", None)),
        tool_calls=tool_calls,
    )


class GeminiLLMClient(LLMClient):
    """Google Gemini implementation of :class:`LLMClient`."""

    provider = "gemini"
    capabilities = capabilities_for("gemini")

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        timeout: float | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
        client: Any = None,
    ) -> None:
        if not model:
            raise ConfigurationError("Gemini provider requires a model name.")
        if client is None:
            if not api_key:
                raise ConfigurationError(
                    "Gemini provider requires an API key (set LLM__GOOGLE_API_KEY)."
                )
            http_options = types.HttpOptions(timeout=int(timeout * 1000)) if timeout else None
            client = genai.Client(api_key=api_key, http_options=http_options)
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def model_name(self) -> str:
        return self._model

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.require(LLMCapability.complete)
        try:
            response = await self._client.aio.models.generate_content(
                model=request.model or self._model,
                contents=_to_contents(request),
                config=self._build_config(request),
            )
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        return _parts_to_response(response, request.model or self._model)

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        self.require(LLMCapability.stream)
        finish = "stop"
        usage: Usage | None = None
        try:
            stream = self._client.aio.models.generate_content_stream(
                model=request.model or self._model,
                contents=_to_contents(request),
                config=self._build_config(request),
            )
            async for chunk in stream:
                candidates = getattr(chunk, "candidates", None) or []
                if candidates:
                    finish = _finish_reason(getattr(candidates[0], "finish_reason", None))
                    content = getattr(candidates[0], "content", None)
                    for part in getattr(content, "parts", None) or []:
                        if part.text:
                            yield StreamChunk(delta=part.text)
                metadata = getattr(chunk, "usage_metadata", None)
                if metadata is not None:
                    usage = _usage_from(metadata)
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        yield StreamChunk(done=True, finish_reason=finish, usage=usage)

    async def structured(
        self,
        request: CompletionRequest,
        schema: type[ModelT],
    ) -> ModelT:
        self.require(LLMCapability.structured)
        config = self._build_config(
            request,
            response_mime_type="application/json",
            response_schema=schema,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=request.model or self._model,
                contents=_to_contents(request),
                config=config,
            )
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed
        text = getattr(response, "text", None)
        if text:
            return schema.model_validate_json(text)
        raise LLMError(
            "Gemini did not return structured output.",
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
        config = self._build_config(request)
        if tools:
            config.tools = [types.Tool(function_declarations=_to_function_declarations(tools))]
            config.tool_config = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=self._tool_mode(tool_choice)
                )
            )
        try:
            response = await self._client.aio.models.generate_content(
                model=request.model or self._model,
                contents=_to_contents(request),
                config=config,
            )
        except Exception as error:
            raise normalize_error(self.provider, error) from error
        return _parts_to_response(response, request.model or self._model)

    async def aclose(self) -> None:
        return None

    # -- internals ---------------------------------------------------------

    def _build_config(
        self,
        request: CompletionRequest,
        *,
        response_mime_type: str | None = None,
        response_schema: Any = None,
    ) -> types.GenerateContentConfig:
        kwargs: dict[str, Any] = {}
        system = _extract_system(request)
        if system is not None:
            kwargs["system_instruction"] = system
        temperature = request.temperature if request.temperature is not None else self._temperature
        if temperature is not None:
            kwargs["temperature"] = temperature
        max_tokens = request.max_tokens or self._max_tokens
        if max_tokens is not None:
            kwargs["max_output_tokens"] = max_tokens
        if request.stop:
            kwargs["stop_sequences"] = list(request.stop)
        if response_mime_type:
            kwargs["response_mime_type"] = response_mime_type
        if response_schema is not None:
            kwargs["response_schema"] = response_schema
        return types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _tool_mode(tool_choice: str | None) -> types.FunctionCallingConfigMode:
        if tool_choice in {"any", "required"}:
            return types.FunctionCallingConfigMode.ANY
        if tool_choice == "none":
            return types.FunctionCallingConfigMode.NONE
        return types.FunctionCallingConfigMode.AUTO
