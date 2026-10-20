"""API tests for conversation endpoints (TASK-035) via dependency override (no live DB)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ecommerce_support.api.dependencies import get_conversation_service
from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.main import create_app
from ecommerce_support.schemas import (
    Conversation,
    ConversationSummary,
    Message,
    Page,
    PageParams,
)
from ecommerce_support.schemas.enums import ConversationStatus, MessageRole

_NOW = datetime(2026, 10, 12, tzinfo=UTC)


class StubConversationService:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.list_calls: list[tuple[str, PageParams]] = []
        self.message_calls: list[tuple[str, PageParams]] = []
        self.not_found = False
        self.owner_id: str | None = None

    def _check(self, user_id: str | None) -> None:
        if self.not_found or user_id != self.owner_id:
            raise NotFoundError("Conversation not found.")

    async def get(self, conversation_id: str, *, user_id: str | None = None) -> Conversation:
        self._check(user_id)
        return Conversation(
            id=conversation_id,
            user_id=self.owner_id,
            status=ConversationStatus.AWAITING_CUSTOMER,
            created_at=_NOW,
            updated_at=_NOW,
            messages=[
                Message(
                    id="msg_1",
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    content="hello",
                    created_at=_NOW,
                )
            ],
        )

    async def assert_access(self, conversation_id: str, *, user_id: str | None = None) -> None:
        self._check(user_id)

    async def list_for_user(
        self, user_id: str, *, params: PageParams | None = None
    ) -> Page[ConversationSummary]:
        params = params or PageParams()
        self.list_calls.append((user_id, params))
        items = [
            ConversationSummary(
                id="conv_1",
                status=ConversationStatus.OPEN,
                created_at=_NOW,
                updated_at=_NOW,
                message_count=2,
            )
        ]
        return Page[ConversationSummary](
            items=items, total=1, limit=params.limit, offset=params.offset
        )

    async def list_messages(
        self, conversation_id: str, *, user_id: str | None = None, params: PageParams | None = None
    ) -> Page[Message]:
        self._check(user_id)
        params = params or PageParams()
        self.message_calls.append((conversation_id, params))
        return Page[Message](
            items=[
                Message(
                    id="msg_1",
                    conversation_id=conversation_id,
                    role=MessageRole.USER,
                    content="hello",
                    created_at=_NOW,
                )
            ],
            total=1,
            limit=params.limit,
            offset=params.offset,
        )

    async def delete(self, conversation_id: str, *, user_id: str | None = None) -> None:
        self._check(user_id)
        self.deleted.append(conversation_id)


@pytest.fixture
def stub_service() -> StubConversationService:
    return StubConversationService()


@pytest.fixture
def api_app(stub_service: StubConversationService, settings) -> FastAPI:
    app = create_app(settings)
    app.dependency_overrides[get_conversation_service] = lambda: stub_service
    return app


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_get_conversation_includes_messages(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/conversations/conv_1")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "conv_1"
    assert body["messages"][0]["content"] == "hello"


async def test_get_conversation_enforces_ownership(
    api_client: AsyncClient, stub_service: StubConversationService, auth_headers
) -> None:
    stub_service.owner_id = "u-1"
    assert (
        await api_client.get("/api/v1/conversations/conv_1", headers=auth_headers("u-1"))
    ).status_code == 200
    cross = await api_client.get("/api/v1/conversations/conv_1", headers=auth_headers("u-2"))
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "not_found"


async def test_get_missing_conversation_returns_404(
    api_client: AsyncClient, stub_service: StubConversationService
) -> None:
    stub_service.not_found = True
    response = await api_client.get("/api/v1/conversations/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_list_conversations_requires_auth(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/conversations")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_list_conversations_is_scoped_to_caller(
    api_client: AsyncClient, stub_service, auth_headers
) -> None:
    response = await api_client.get(
        "/api/v1/conversations",
        params={"limit": 5, "offset": 10},
        headers=auth_headers("u-1"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 5
    assert body["offset"] == 10
    assert body["items"][0]["id"] == "conv_1"
    assert stub_service.list_calls[0][0] == "u-1"


async def test_get_conversation_history_is_paginated(api_client: AsyncClient, stub_service) -> None:
    response = await api_client.get(
        "/api/v1/conversations/conv_1/messages",
        params={"limit": 5, "offset": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 5
    assert body["offset"] == 2
    assert body["items"][0]["content"] == "hello"
    assert stub_service.message_calls[0][0] == "conv_1"
    assert stub_service.message_calls[0][1].limit == 5


async def test_get_history_unknown_conversation_returns_404(
    api_client: AsyncClient, stub_service: StubConversationService
) -> None:
    stub_service.not_found = True
    assert (await api_client.get("/api/v1/conversations/missing/messages")).status_code == 404


async def test_delete_conversation(api_client: AsyncClient, stub_service) -> None:
    response = await api_client.delete("/api/v1/conversations/conv_1")
    assert response.status_code == 204
    assert stub_service.deleted == ["conv_1"]


async def test_delete_missing_returns_404(
    api_client: AsyncClient, stub_service: StubConversationService
) -> None:
    stub_service.not_found = True
    assert (await api_client.delete("/api/v1/conversations/missing")).status_code == 404
