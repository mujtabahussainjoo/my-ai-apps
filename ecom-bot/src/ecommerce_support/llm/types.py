"""Provider-independent LLM data contracts.

These types are the only vocabulary agents/tools use to talk to an LLM. No provider SDK
types leak across this boundary (NFR-007). They are plain Pydantic models so the layer is
testable without any provider runtime.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

JSONDict = dict[str, Any]


class Role(StrEnum):
    """Conversation role for a single message."""

    system = "system"
    user = "user"
    assistant = "assistant"
    tool = "tool"


class LLMType(BaseModel):
    """Base for LLM-layer models: strict about unknown fields, never strips content."""

    model_config = ConfigDict(extra="forbid")


class ToolCall(LLMType):
    """A model-requested invocation of a registered tool."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: JSONDict = Field(default_factory=dict)


class ToolDefinition(LLMType):
    """A tool exposed to the model, described by a JSON-schema-style parameter object."""

    name: str = Field(min_length=1)
    description: str = ""
    parameters: JSONDict = Field(default_factory=dict)


class ToolCallResult(LLMType):
    """The result of running a tool call, fed back to the model."""

    tool_call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    content: str = ""
    is_error: bool = False


class ChatMessage(LLMType):
    """One provider-neutral conversation message."""

    role: Role
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class Usage(LLMType):
    """Token/cost accounting attached to every completed result."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)


class CompletionRequest(LLMType):
    """A generic, provider-independent generation request."""

    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None
    system: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    stop: list[str] = Field(default_factory=list)
    metadata: JSONDict = Field(default_factory=dict)


class CompletionResponse(LLMType):
    """A completed generation. ``tool_calls`` is populated for tool-calling turns."""

    content: str = ""
    model: str
    finish_reason: str = "stop"
    usage: Usage = Field(default_factory=Usage)
    tool_calls: list[ToolCall] = Field(default_factory=list)


class StreamChunk(LLMType):
    """A single streamed delta. The terminal chunk has ``done=True``."""

    delta: str = ""
    done: bool = False
    finish_reason: str | None = None
    usage: Usage | None = None
