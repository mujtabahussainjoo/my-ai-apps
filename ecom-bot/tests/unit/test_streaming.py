"""Unit tests for SSE event schemas and encoding (TASK-036, FR-010/FR-014)."""

from __future__ import annotations

from pydantic import TypeAdapter

from ecommerce_support.schemas import (
    ErrorEvent,
    MessageEndEvent,
    MessageStartEvent,
    StreamEvent,
    TokenEvent,
    ToolResultEvent,
    encode_sse,
)
from ecommerce_support.schemas.enums import ConversationStatus

_adapter = TypeAdapter(StreamEvent)


def test_encode_sse_frame_shape() -> None:
    frame = encode_sse(TokenEvent(conversation_id="c1", request_id="r1", text="hi "))
    assert frame.startswith("event: token\ndata: ")
    assert frame.endswith("\n\n")
    assert frame.count("\ndata: ") == 1
    assert '"conversation_id":"c1"' in frame
    assert '"request_id":"r1"' in frame
    assert '"text":"hi "' in frame


def test_encode_sse_excludes_none_fields() -> None:
    frame = encode_sse(MessageStartEvent(conversation_id="c1"))
    assert "request_id" not in frame
    assert '"conversation_id":"c1"' in frame


def test_encode_sse_payload_is_single_line() -> None:
    frame = encode_sse(TokenEvent(text="line one\nline two"))
    lines = frame.rstrip("\n").split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: token"
    assert lines[1].startswith("data: {")
    # The embedded newline is JSON-escaped, so it stays on the single data line.
    assert "\\n" in lines[1]


def test_event_union_discriminates_on_event_field() -> None:
    parsed = _adapter.validate_python(
        {"event": "message_start", "conversation_id": "c1", "request_id": "r1"}
    )
    assert isinstance(parsed, MessageStartEvent)

    error = _adapter.validate_python(
        {"event": "error", "code": "internal_error", "message": "boom", "retryable": True}
    )
    assert isinstance(error, ErrorEvent)
    assert error.retryable is True


def test_event_roundtrip_json() -> None:
    original = MessageEndEvent(
        conversation_id="c1",
        request_id="r1",
        message_id="m1",
        content="done",
        conversation_status=ConversationStatus.RESOLVED,
    )
    parsed = _adapter.validate_json(original.model_dump_json())
    assert parsed == original


def test_token_preserves_whitespace() -> None:
    token = TokenEvent(text="  spaced  ")
    assert token.text == "  spaced  "


def test_tool_result_carries_no_raw_output() -> None:
    event = ToolResultEvent(tool="order_lookup", call_id="c1", status="ok", summary="found 1")
    payload = event.model_dump()
    assert set(payload) == {
        "event",
        "conversation_id",
        "request_id",
        "tool",
        "call_id",
        "status",
        "summary",
    }
