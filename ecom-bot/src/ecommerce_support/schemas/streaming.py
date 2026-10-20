"""Typed server-sent-event contracts for streaming chat (FR-010, FR-014).

Every event carries the conversation and request correlation ids (FR-005). Only customer-visible
data is included: ``token`` events carry answer text, ``tool_*`` events carry a tool name/status
(never raw arguments or outputs, FR-011), and ``error`` events carry a safe code/message.

The union is discriminated on the ``event`` field so :func:`encode_sse` and OpenAPI documents
both resolve the concrete payload.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from ecommerce_support.schemas.agents import SourceCitation
from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.enums import (
    ConversationStatus,
    ResolutionOutcome,
    TicketProvider,
    TicketStatus,
)


class StreamEventBase(Schema):
    """Fields shared by every stream event (FR-005)."""

    event: str = ""
    conversation_id: str | None = Field(default=None, max_length=64)
    request_id: str | None = Field(default=None, max_length=128)


class MessageStartEvent(StreamEventBase):
    """The turn has started; the conversation id is known."""

    event: Literal["message_start"] = "message_start"


class TokenEvent(StreamEventBase):
    """A chunk of answer text preserving its original whitespace (FR-010).

    Whitespace is significant here — concatenating ``text`` across ``token`` events must
    reconstruct the answer exactly — so this event opts out of the shared strip-whitespace rule.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    event: Literal["token"] = "token"
    text: str = ""


class ToolStartEvent(StreamEventBase):
    """A tool invocation began (name only; no arguments, FR-011)."""

    event: Literal["tool_start"] = "tool_start"
    tool: str = Field(min_length=1)
    call_id: str | None = None


class ToolResultEvent(StreamEventBase):
    """A tool invocation finished (safe status/summary; no raw output, FR-011)."""

    event: Literal["tool_result"] = "tool_result"
    tool: str = Field(min_length=1)
    call_id: str | None = None
    status: str = Field(min_length=1)
    summary: str = ""


class SourceEvent(StreamEventBase):
    """Retrieved policy evidence grounding the answer (FR-033)."""

    event: Literal["source"] = "source"
    citations: list[SourceCitation] = Field(default_factory=list)


class TicketCreatedEvent(StreamEventBase):
    """A support ticket was created (or reused) for the escalation (FR-044/FR-053)."""

    event: Literal["ticket_created"] = "ticket_created"
    ticket_id: str | None = None
    external_id: str | None = None
    provider: TicketProvider | None = None
    status: TicketStatus | None = None
    url: str | None = None


class ErrorEvent(StreamEventBase):
    """A failure after streaming began; always followed by ``message_end`` (FR-012)."""

    event: Literal["error"] = "error"
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False


class MessageEndEvent(StreamEventBase):
    """Terminal event: the persisted assistant message and final conversation status."""

    event: Literal["message_end"] = "message_end"
    message_id: str | None = None
    content: str = ""
    resolution_state: ResolutionOutcome | None = None
    conversation_status: ConversationStatus | None = None


StreamEvent = Annotated[
    MessageStartEvent
    | TokenEvent
    | ToolStartEvent
    | ToolResultEvent
    | SourceEvent
    | TicketCreatedEvent
    | ErrorEvent
    | MessageEndEvent,
    Field(discriminator="event"),
]


def encode_sse(event: StreamEventBase) -> str:
    """Render an event as a single SSE frame (``event:`` + one-line ``data:``).

    ``model_dump_json`` never emits raw newlines, so the payload stays on one ``data:`` line per
    the SSE grammar.
    """
    return f"event: {event.event}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"


__all__ = [
    "ErrorEvent",
    "MessageEndEvent",
    "MessageStartEvent",
    "SourceEvent",
    "StreamEvent",
    "StreamEventBase",
    "TicketCreatedEvent",
    "TokenEvent",
    "ToolResultEvent",
    "ToolStartEvent",
    "encode_sse",
]
