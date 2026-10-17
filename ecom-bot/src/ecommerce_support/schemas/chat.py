"""Chat and conversation contracts for the API and services layer."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from ecommerce_support.schemas.agents import SourceCitation, ToolExecution
from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.enums import (
    AgentName,
    ConversationStatus,
    MessageRole,
    ResolutionOutcome,
)

# Mirrors LIMITS config defaults; the service layer enforces the configured value.
MAX_MESSAGE_CHARS = 4000
MAX_CONTENT_CHARS = 20000


class ChatRequest(Schema):
    """Inbound chat turn (FR-001, FR-003)."""

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)
    stream: bool = True

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must contain non-whitespace characters")
        return value


class MessageCreate(Schema):
    """A message to be persisted against a conversation."""

    role: MessageRole
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    agent: AgentName | None = None


class Message(Schema):
    """A persisted conversation message with optional evidence and tool activity."""

    id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    role: MessageRole
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    created_at: datetime
    agent: AgentName | None = None
    sources: list[SourceCitation] = Field(default_factory=list)
    tool_executions: list[ToolExecution] = Field(default_factory=list)


class Conversation(Schema):
    """A conversation with its ordered messages (FR-002)."""

    id: str = Field(min_length=1)
    user_id: str | None = None
    status: ConversationStatus = ConversationStatus.OPEN
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = Field(default_factory=list)


class ConversationSummary(Schema):
    """Lightweight conversation projection for list endpoints."""

    id: str = Field(min_length=1)
    status: ConversationStatus = ConversationStatus.OPEN
    created_at: datetime
    updated_at: datetime
    message_count: int = Field(default=0, ge=0)


class ChatResponse(Schema):
    """Non-streaming chat result (FR-003, FR-005)."""

    conversation_id: str = Field(min_length=1)
    message: Message
    resolution_state: ResolutionOutcome | None = None
    request_id: str | None = None
