"""Conversation use-cases: read history and delete conversation data (FR-002, FR-012, SEC-002).

Framework-free; the route layer only translates HTTP to these calls and passes the caller's
identity down. Ownership is enforced **here** (in application code, never by prompt): a caller may
only read or delete a conversation whose ``user_id`` matches theirs (guests own conversations with
``user_id IS NULL``). A mismatch is reported as ``not found`` so existence is not leaked.
"""

from __future__ import annotations

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.db.repositories import ConversationRepository, ToolExecutionRepository
from ecommerce_support.schemas import Conversation, ConversationSummary, Message, Page, PageParams


class ConversationService:
    """Reads conversations and erases them on request, enforcing ownership."""

    def __init__(
        self,
        conversations: ConversationRepository,
        tool_executions: ToolExecutionRepository | None = None,
    ) -> None:
        self._conversations = conversations
        self._tool_executions = tool_executions

    async def get(self, conversation_id: str, *, user_id: str | None) -> Conversation:
        conversation = await self.assert_access(conversation_id, user_id=user_id)
        messages = await self._attach_tool_executions(conversation.messages)
        return conversation.model_copy(update={"messages": messages})

    async def assert_access(self, conversation_id: str, *, user_id: str | None) -> Conversation:
        """Return the conversation when the caller owns it, else raise ``not found``."""
        conversation = await self._conversations.get(conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise NotFoundError(
                "Conversation not found.", details={"conversation_id": conversation_id}
            )
        return conversation

    async def list_messages(
        self, conversation_id: str, *, user_id: str | None, params: PageParams | None = None
    ) -> Page[Message]:
        """Return a paginated, oldest-first slice of the conversation's message history."""
        await self.assert_access(conversation_id, user_id=user_id)
        params = params or PageParams()
        messages, total = await self._conversations.list_messages(
            conversation_id, limit=params.limit, offset=params.offset
        )
        return Page[Message](
            items=await self._attach_tool_executions(messages),
            total=total,
            limit=params.limit,
            offset=params.offset,
        )

    async def list_for_user(
        self, user_id: str, *, params: PageParams | None = None
    ) -> Page[ConversationSummary]:
        params = params or PageParams()
        items, total = await self._conversations.list_for_user(
            user_id, limit=params.limit, offset=params.offset
        )
        return Page[ConversationSummary](
            items=items, total=total, limit=params.limit, offset=params.offset
        )

    async def delete(self, conversation_id: str, *, user_id: str | None) -> None:
        """Erase a conversation and everything attached to it, if the caller owns it (FR-012)."""
        await self.assert_access(conversation_id, user_id=user_id)
        await self._conversations.delete(conversation_id)

    async def _attach_tool_executions(self, messages: list[Message]) -> list[Message]:
        if self._tool_executions is None or not messages:
            return messages
        grouped = await self._tool_executions.list_by_message_ids([m.id for m in messages])
        return [
            message.model_copy(update={"tool_executions": grouped.get(message.id, [])})
            for message in messages
        ]


__all__ = ["ConversationService"]
