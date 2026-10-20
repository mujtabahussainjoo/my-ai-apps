"""API tests for chat endpoints (TASK-035/036) via dependency override (no live DB)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ecommerce_support.api.dependencies import get_chat_service
from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.main import create_app
from ecommerce_support.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorEvent,
    Message,
    MessageEndEvent,
    MessageStartEvent,
    StreamEventBase,
    TokenEvent,
)
from ecommerce_support.schemas.enums import ConversationStatus, MessageRole

_NOW = datetime(2026, 10, 12, tzinfo=UTC)


class StubChatService:
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []
        self.user_ids: list[str | None] = []
        self.not_found = False

    async def chat(
        self,
        request: ChatRequest,
        *,
        user_id: str | None = None,
        tenant_id: str = "default",
        request_id: str | None = None,
    ) -> ChatResponse:
        if self.not_found:
            raise NotFoundError("Conversation not found.")
        self.requests.append(request)
        self.user_ids.append(user_id)
        conversation_id = request.conversation_id or "conv_1"
        return ChatResponse(
            conversation_id=conversation_id,
            message=Message(
                id="msg_1",
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="Hello!",
                created_at=_NOW,
            ),
            request_id=request_id,
        )

    async def stream(
        self,
        request: ChatRequest,
        *,
        user_id: str | None = None,
        tenant_id: str = "default",
        request_id: str | None = None,
    ) -> AsyncIterator[StreamEventBase]:
        self.requests.append(request)
        self.user_ids.append(user_id)
        conversation_id = request.conversation_id or "conv_1"
        if self.not_found:
            yield ErrorEvent(
                conversation_id=request.conversation_id,
                request_id=request_id,
                code="not_found",
                message="Conversation not found.",
            )
            yield MessageEndEvent(conversation_id=request.conversation_id, request_id=request_id)
            return
        yield MessageStartEvent(conversation_id=conversation_id, request_id=request_id)
        yield TokenEvent(conversation_id=conversation_id, request_id=request_id, text="Hello")
        yield MessageEndEvent(
            conversation_id=conversation_id,
            request_id=request_id,
            message_id="msg_1",
            content="Hello",
            conversation_status=ConversationStatus.AWAITING_CUSTOMER,
        )


@pytest.fixture
def stub_service() -> StubChatService:
    return StubChatService()


@pytest.fixture
def api_app(stub_service: StubChatService, settings) -> FastAPI:
    app = create_app(settings)
    app.dependency_overrides[get_chat_service] = lambda: stub_service
    return app


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_chat_json_mode_returns_assistant_message(
    api_client: AsyncClient, stub_service
) -> None:
    response = await api_client.post("/api/v1/chat", json={"message": "hi", "stream": False})
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv_1"
    assert body["message"]["content"] == "Hello!"
    assert len(stub_service.requests) == 1


async def test_chat_uses_authenticated_user(
    api_client: AsyncClient, stub_service, auth_headers
) -> None:
    await api_client.post(
        "/api/v1/chat",
        json={"message": "hi", "stream": False},
        headers=auth_headers("u-7"),
    )
    assert stub_service.user_ids == ["u-7"]


async def test_chat_rejects_blank_message(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/chat", json={"message": "   "})
    assert response.status_code == 422


async def test_chat_streams_typed_events(api_client: AsyncClient) -> None:
    async with api_client.stream(
        "POST", "/api/v1/chat", json={"message": "hi", "stream": True}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = (await response.aread()).decode()
    assert "event: message_start" in body
    assert "event: token" in body
    assert '"text":"Hello"' in body
    assert "event: message_end" in body
    assert body.rstrip().endswith("}")


async def test_chat_stream_unknown_conversation_emits_error(
    api_client: AsyncClient, stub_service: StubChatService
) -> None:
    stub_service.not_found = True
    async with api_client.stream(
        "POST",
        "/api/v1/chat",
        json={"message": "hi", "conversation_id": "missing", "stream": True},
    ) as response:
        assert response.status_code == 200
        body = (await response.aread()).decode()
    assert "event: error" in body
    assert "event: message_end" in body


async def test_chat_json_unknown_conversation_returns_404(
    api_client: AsyncClient, stub_service: StubChatService
) -> None:
    stub_service.not_found = True
    response = await api_client.post(
        "/api/v1/chat", json={"message": "hi", "conversation_id": "missing", "stream": False}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
