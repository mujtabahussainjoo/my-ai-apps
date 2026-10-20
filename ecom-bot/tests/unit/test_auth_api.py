"""API tests for authentication, authorization and rate limiting (TASK-038, SEC-001/012/NFR-004)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ecommerce_support.api.dependencies import get_chat_service, get_settings_dep
from ecommerce_support.core.config import LimitsConfig
from ecommerce_support.main import create_app
from ecommerce_support.schemas import ChatRequest, ChatResponse, Message
from ecommerce_support.schemas.enums import MessageRole

_NOW = datetime(2026, 10, 19, tzinfo=UTC)


class StubChatService:
    async def chat(
        self,
        request: ChatRequest,
        *,
        user_id: str | None = None,
        tenant_id: str = "default",
        request_id: str | None = None,
    ) -> ChatResponse:
        return ChatResponse(
            conversation_id=request.conversation_id or "conv_1",
            message=Message(
                id="msg_1",
                conversation_id="conv_1",
                role=MessageRole.ASSISTANT,
                content="ok",
                created_at=_NOW,
            ),
            request_id=request_id,
        )


@pytest.fixture
def api_app(settings, auth_headers) -> FastAPI:
    limited = settings.model_copy(update={"limits": LimitsConfig(rate_limit_per_minute=1)})
    app = create_app(limited)
    app.dependency_overrides[get_settings_dep] = lambda: limited
    app.dependency_overrides[get_chat_service] = lambda: StubChatService()
    return app


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_invalid_token_returns_401(api_client: AsyncClient) -> None:
    response = await api_client.get(
        "/api/v1/conversations", headers={"Authorization": "Bearer not-a-token"}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "authentication_error"


async def test_non_bearer_scheme_returns_401(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/conversations", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401


async def test_guest_chat_is_allowed(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/chat", json={"message": "hi", "stream": False})
    assert response.status_code == 200


async def test_chat_rate_limit_returns_429_with_retry_after(
    api_client: AsyncClient, auth_headers
) -> None:
    headers = auth_headers("u-1")
    first = await api_client.post(
        "/api/v1/chat", json={"message": "hi", "stream": False}, headers=headers
    )
    assert first.status_code == 200
    second = await api_client.post(
        "/api/v1/chat", json={"message": "hi", "stream": False}, headers=headers
    )
    assert second.status_code == 429
    retry_after = second.headers["retry-after"]
    assert int(retry_after) >= 1
    assert second.json()["error"]["details"]["retry_after_seconds"] == int(retry_after)
