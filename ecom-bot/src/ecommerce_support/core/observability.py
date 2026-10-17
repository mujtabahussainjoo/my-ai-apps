"""Request/trace correlation primitives.

Correlation IDs live in :mod:`contextvars` so that logging, tools, and the DB layer can
attach them without threading parameters through every call.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_conversation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "conversation_id", default=None
)


def new_id(prefix: str = "") -> str:
    """Return a short, URL-safe unique id, optionally prefixed (e.g. ``req_``)."""
    token = uuid.uuid4().hex
    return f"{prefix}{token}" if prefix else token


def new_trace_id() -> str:
    return new_id("trace_")


def current_request_id() -> str | None:
    return _request_id.get()


def current_conversation_id() -> str | None:
    return _conversation_id.get()


@contextmanager
def request_context(
    request_id: str | None = None, conversation_id: str | None = None
) -> Iterator[str]:
    """Bind correlation ids for the duration of the block; yields the request id."""
    rid = request_id or new_id("req_")
    token_r = _request_id.set(rid)
    token_c = _conversation_id.set(conversation_id)
    try:
        yield rid
    finally:
        _request_id.reset(token_r)
        _conversation_id.reset(token_c)


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Immutable snapshot of correlation data for logging/tracing."""

    request_id: str | None
    conversation_id: str | None

    @classmethod
    def current(cls) -> TraceContext:
        return cls(request_id=current_request_id(), conversation_id=current_conversation_id())
