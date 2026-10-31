"""Provider-neutral request/response models and the :class:`Provider` interface."""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexapilot.core.errors import NexaPilotError

Role = Literal["system", "user", "assistant", "tool"]
FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "error"]


class ProviderCapabilities(BaseModel):
    """Capabilities a concrete model/provider actually supports."""

    model_config = ConfigDict(frozen=True)

    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    system_prompt: bool = True
    vision: bool = False
    max_context_tokens: int | None = None

    def missing(self, required: Sequence[str]) -> list[str]:
        return [name for name in required if not getattr(self, name, False)]


class ChatMessage(BaseModel):
    role: Role
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def _content_is_text(cls, value: str) -> str:
        return value or ""


class ToolDefinition(BaseModel):
    """A tool advertised to the model."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})

    def model_post_init(self, _context: Any) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError(f"invalid tool name: {self.name!r}")


class ToolCall(BaseModel):
    id: str = ""
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float | None = None
    max_output_tokens: int | None = None
    tools: list[ToolDefinition] = Field(default_factory=list)
    tool_choice: str | None = None
    response_schema: dict[str, Any] | None = None
    stop: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = None

    @field_validator("messages")
    @classmethod
    def _messages_not_empty(cls, value: list[ChatMessage]) -> list[ChatMessage]:
        if not value:
            raise ValueError("at least one message is required")
        return value


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ChatResponse(BaseModel):
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason = "stop"
    usage: TokenUsage = Field(default_factory=TokenUsage)
    provider: str = ""
    model: str = ""
    request_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


StreamEventType = Literal["text", "tool_call", "usage", "done", "error"]


class StreamEvent(BaseModel):
    """A single event emitted while streaming a response."""

    type: StreamEventType
    text: str = ""
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None
    finish_reason: FinishReason | None = None
    error: dict[str, Any] | None = None


class ConnectionTestResult(BaseModel):
    ok: bool
    provider: str
    model: str = ""
    message: str = ""
    latency_ms: int | None = None
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    error_code: str | None = None


class ProviderUnavailable(NexaPilotError):
    code = "provider_unavailable"
    http_status = 503


class Provider(abc.ABC):
    """Common interface implemented by every model provider adapter."""

    provider_id: str = "unknown"
    display_name: str = "Unknown provider"
    default_base_url: str = ""
    requires_api_key: bool = True
    supports_custom_base_url: bool = True

    def __init__(self, *, model: str, base_url: str = "", api_key: str = "") -> None:
        self.model = model
        self.base_url = (base_url or self.default_base_url).rstrip("/")
        self._api_key = api_key

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def require_capability(self, *names: str) -> None:
        missing = self.capabilities.missing(names)
        if missing:
            from nexapilot.core.errors import CapabilityNotSupportedError

            raise CapabilityNotSupportedError(
                f"{self.display_name} does not support: {', '.join(missing)}",
                details={"provider": self.provider_id, "missing": missing},
            )

    @abc.abstractmethod
    async def generate(self, request: ChatRequest) -> ChatResponse: ...

    @abc.abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]: ...

    @abc.abstractmethod
    async def list_models(self) -> list[str]: ...

    async def test_connection(self) -> ConnectionTestResult:
        """Perform a minimal round-trip to validate the configuration."""
        import time

        started = time.perf_counter()
        try:
            await self.generate(
                ChatRequest(
                    model=self.model,
                    messages=[ChatMessage(role="user", content="Reply with the single word: ok")],
                    max_output_tokens=16,
                    timeout_seconds=30.0,
                )
            )
        except NexaPilotError as exc:
            return ConnectionTestResult(
                ok=False,
                provider=self.provider_id,
                model=self.model,
                message=exc.message,
                error_code=exc.code,
                capabilities=self.capabilities,
            )
        latency = int((time.perf_counter() - started) * 1000)
        return ConnectionTestResult(
            ok=True,
            provider=self.provider_id,
            model=self.model,
            message="Connection successful",
            latency_ms=latency,
            capabilities=self.capabilities,
        )


ChatMessage.model_rebuild()
