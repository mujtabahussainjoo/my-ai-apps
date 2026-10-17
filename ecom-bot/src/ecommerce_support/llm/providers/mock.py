"""Deterministic in-process LLM client used by tests and offline demos (D-004, NFR-008).

Supports every capability so the mock can stand in for a real provider anywhere. Responses
are scriptable via queues for exact test assertions, with a deterministic echo fallback so
the client is useful without any setup.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic import BaseModel

from ecommerce_support.core.exceptions import LLMError
from ecommerce_support.llm.base import LLMClient, ModelT
from ecommerce_support.llm.capabilities import LLMCapability
from ecommerce_support.llm.types import (
    CompletionRequest,
    CompletionResponse,
    Role,
    StreamChunk,
    ToolCall,
    ToolDefinition,
    Usage,
)

ScriptedCompletion = CompletionResponse | str
ScriptedStructured = BaseModel | dict[str, Any]


class MockLLMClient(LLMClient):
    """An LLM client that returns deterministic, offline responses.

    Args:
        name: model identifier reported by :meth:`model_name`.
        echo_prefix: prefix used by the default (unscripted) completion.
        chunk_size: number of characters per streamed :class:`StreamChunk`.
        completions: optional queue of scripted completions consumed by ``complete``/``astream``.
        structured_outputs: optional queue consumed by ``structured`` (models or dicts).
        tool_call_responses: optional queue consumed by ``tool_call``.
    """

    provider = "mock"
    capabilities = frozenset(
        {
            LLMCapability.complete,
            LLMCapability.stream,
            LLMCapability.structured,
            LLMCapability.tool_calling,
        }
    )

    def __init__(
        self,
        *,
        name: str = "mock-1",
        echo_prefix: str = "[mock]",
        chunk_size: int = 8,
        completions: Sequence[ScriptedCompletion] | None = None,
        structured_outputs: Sequence[ScriptedStructured] | None = None,
        tool_call_responses: Sequence[Sequence[ToolCall]] | None = None,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")
        self._name = name
        self._echo_prefix = echo_prefix
        self._chunk_size = chunk_size
        self._scripted_completions: list[ScriptedCompletion] = list(completions or [])
        self._scripted_structured: list[ScriptedStructured] = list(structured_outputs or [])
        self._scripted_tool_calls: list[list[ToolCall]] = [
            list(calls) for calls in (tool_call_responses or [])
        ]
        self.requests: list[CompletionRequest] = []
        self.structured_requests: list[CompletionRequest] = []
        self.tool_requests: list[tuple[CompletionRequest, tuple[ToolDefinition, ...]]] = []

    def model_name(self) -> str:
        return self._name

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.require(LLMCapability.complete)
        self.requests.append(request)
        return self._next_completion(request)

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        self.require(LLMCapability.stream)
        self.requests.append(request)
        response = self._next_completion(request)
        content = response.content
        for start in range(0, len(content), self._chunk_size):
            yield StreamChunk(delta=content[start : start + self._chunk_size])
        yield StreamChunk(
            done=True,
            finish_reason=response.finish_reason,
            usage=response.usage,
        )

    async def structured(
        self,
        request: CompletionRequest,
        schema: type[ModelT],
    ) -> ModelT:
        self.require(LLMCapability.structured)
        self.structured_requests.append(request)
        if not self._scripted_structured:
            raise LLMError(
                f"MockLLMClient has no scripted structured output for {schema.__name__}.",
                details={"schema": schema.__name__},
            )
        item = self._scripted_structured.pop(0)
        if isinstance(item, schema):
            return item
        if isinstance(item, BaseModel):
            raise LLMError(
                f"Scripted structured output is {type(item).__name__}, expected {schema.__name__}.",
                details={"schema": schema.__name__, "got": type(item).__name__},
            )
        return schema.model_validate(item)

    async def tool_call(
        self,
        request: CompletionRequest,
        tools: Sequence[ToolDefinition],
        *,
        tool_choice: str | None = None,
    ) -> CompletionResponse:
        self.require(LLMCapability.tool_calling)
        tool_tuple = tuple(tools)
        self.tool_requests.append((request, tool_tuple))
        calls = self._scripted_tool_calls.pop(0) if self._scripted_tool_calls else []
        return CompletionResponse(
            content="",
            model=self._resolved_model(request),
            finish_reason="tool_calls" if calls else "stop",
            usage=self._estimate_usage(request, ""),
            tool_calls=calls,
        )

    # -- internals ---------------------------------------------------------

    def _resolved_model(self, request: CompletionRequest) -> str:
        return request.model or self._name

    def _next_completion(self, request: CompletionRequest) -> CompletionResponse:
        if self._scripted_completions:
            item = self._scripted_completions.pop(0)
            if isinstance(item, CompletionResponse):
                return item
            return CompletionResponse(
                content=item,
                model=self._resolved_model(request),
                usage=self._estimate_usage(request, item),
            )
        content = self._default_content(request)
        return CompletionResponse(
            content=content,
            model=self._resolved_model(request),
            usage=self._estimate_usage(request, content),
        )

    def _default_content(self, request: CompletionRequest) -> str:
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role is Role.user),
            "",
        )
        if last_user:
            return f"{self._echo_prefix} {last_user}".strip()
        return self._echo_prefix

    def _estimate_usage(self, request: CompletionRequest, content: str) -> Usage:
        prompt_tokens = sum(len(m.content.split()) for m in request.messages)
        completion_tokens = len(content.split())
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )
