"""End-to-end conversation history, pagination, and ownership enforcement (mocks only)."""

from __future__ import annotations

from typing import Any

import pytest

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.schemas import ChatRequest, PageParams
from ecommerce_support.schemas.enums import MessageRole

pytestmark = pytest.mark.e2e


async def _turn(stack: Any, message: str, *, user_id: str = "cust-1", **kwargs: object):
    return await stack.chat.chat(ChatRequest(message=message, **kwargs), user_id=user_id)


class TestConversationHistory:
    async def test_history_returns_ordered_messages(self, e2e_stack: Any) -> None:
        await _turn(e2e_stack, "Where is my order ord-1?")
        first = e2e_stack.conversations_store.conversations
        conversation_id = next(iter(first))
        page = await e2e_stack.conversations.list_messages(conversation_id, user_id="cust-1")
        assert [m.role for m in page.items] == [MessageRole.USER, MessageRole.ASSISTANT]
        assert page.total == 2

    async def test_list_for_user_only_returns_owned(self, e2e_stack: Any) -> None:
        response = await _turn(e2e_stack, "Where is my order ord-1?")
        page = await e2e_stack.conversations.list_for_user("cust-1")
        assert [c.id for c in page.items] == [response.conversation_id]

    async def test_pagination_limit_and_offset(self, e2e_stack: Any) -> None:
        response = await _turn(e2e_stack, "Where is my order ord-1?")
        page = await e2e_stack.conversations.list_messages(
            response.conversation_id,
            user_id="cust-1",
            params=PageParams(limit=1, offset=0),
        )
        assert len(page.items) == 1
        assert page.has_more is True

    async def test_delete_removes_conversation(self, e2e_stack: Any) -> None:
        response = await _turn(e2e_stack, "Where is my order ord-1?")
        await e2e_stack.conversations.delete(response.conversation_id, user_id="cust-1")
        assert response.conversation_id not in e2e_stack.conversations_store.conversations


class TestOwnership:
    async def test_cross_customer_access_is_not_found(self, e2e_stack: Any) -> None:
        response = await _turn(e2e_stack, "Where is my order ord-1?")
        with pytest.raises(NotFoundError):
            await e2e_stack.conversations.get(response.conversation_id, user_id="cust-2")

    async def test_cross_customer_delete_is_not_found(self, e2e_stack: Any) -> None:
        response = await _turn(e2e_stack, "Where is my order ord-1?")
        with pytest.raises(NotFoundError):
            await e2e_stack.conversations.delete(response.conversation_id, user_id="cust-2")

    async def test_continuing_another_customers_conversation_is_not_found(
        self, e2e_stack: Any
    ) -> None:
        response = await _turn(e2e_stack, "Where is my order ord-1?", user_id="cust-1")
        with pytest.raises(NotFoundError):
            await _turn(
                e2e_stack,
                "hello",
                user_id="cust-2",
                conversation_id=response.conversation_id,
            )
