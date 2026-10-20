"""Chat endpoint (FR-001, FR-003, FR-010).

``POST /api/v1/chat`` streams typed lifecycle events as server-sent events by default; send
``stream=false`` for the non-streaming JSON mode used by simple clients and tests (FR-003).
Event schemas live in :mod:`ecommerce_support.schemas.streaming` and are documented in
``docs/streaming.md`` (FR-014).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ecommerce_support.api.dependencies import (
    enforce_chat_rate_limit,
    get_chat_service,
    get_request_id,
    get_user_id,
)
from ecommerce_support.schemas import ChatRequest, ChatResponse, StreamEventBase, encode_sse
from ecommerce_support.services import ChatService

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def _as_sse(events: AsyncIterator[StreamEventBase]) -> AsyncIterator[str]:
    async for event in events:
        yield encode_sse(event)


@router.post(
    "",
    response_model=None,
    dependencies=[Depends(enforce_chat_rate_limit)],
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Typed SSE stream (FR-010). JSON when ``stream=false`` (FR-003).",
        }
    },
    summary="Send a chat message",
    description=(
        "Process a customer message and stream typed lifecycle events "
        "(`message_start`, `token`, `tool_start`, `tool_result`, `source`, `ticket_created`, "
        "`error`, `message_end`). Set `stream=false` to receive a single JSON `ChatResponse`."
    ),
)
async def send_message(
    request: ChatRequest,
    user_id: str | None = Depends(get_user_id),
    request_id: str = Depends(get_request_id),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse | StreamingResponse:
    rid = request_id or None
    if not request.stream:
        return await service.chat(request, user_id=user_id, request_id=rid)
    events = service.stream(request, user_id=user_id, request_id=rid)
    return StreamingResponse(_as_sse(events), media_type="text/event-stream", headers=SSE_HEADERS)
