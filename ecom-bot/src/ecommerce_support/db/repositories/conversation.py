"""Conversation and message repository."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import Conversation as ConversationRow
from ecommerce_support.db.models import Message as MessageRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import Conversation, ConversationSummary, Message
from ecommerce_support.schemas.enums import (
    AgentName,
    ConversationStatus,
    MessageRole,
    ResolutionOutcome,
)


def _to_message(row: MessageRow) -> Message:
    return Message(
        id=row.id,
        conversation_id=row.conversation_id,
        role=row.role,
        content=row.content,
        created_at=row.created_at,
        agent=row.agent,
    )


def _to_conversation(row: ConversationRow, *, include_messages: bool) -> Conversation:
    return Conversation(
        id=row.id,
        user_id=row.user_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        messages=[_to_message(m) for m in row.messages] if include_messages else [],
    )


class ConversationRepository(BaseRepository):
    """Persistence for conversations and their messages (FR-002, FR-009)."""

    async def create(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str = "default",
        conversation_id: str | None = None,
        status: ConversationStatus = ConversationStatus.OPEN,
    ) -> Conversation:
        row = ConversationRow(
            id=conversation_id or new_id("conv"),
            user_id=user_id,
            tenant_id=tenant_id,
            status=status,
        )
        self.session.add(row)
        await self.session.flush()
        return _to_conversation(row, include_messages=False)

    async def get(self, conversation_id: str) -> Conversation | None:
        row = await self.session.scalar(
            select(ConversationRow)
            .where(ConversationRow.id == conversation_id)
            .options(selectinload(ConversationRow.messages))
        )
        return _to_conversation(row, include_messages=True) if row is not None else None

    async def get_summary(self, conversation_id: str) -> ConversationSummary | None:
        row = await self.session.get(ConversationRow, conversation_id)
        if row is None:
            return None
        count = await self.session.scalar(
            select(func.count())
            .select_from(MessageRow)
            .where(MessageRow.conversation_id == conversation_id)
        )
        return ConversationSummary(
            id=row.id,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            message_count=int(count or 0),
        )

    async def append_message(
        self,
        conversation_id: str,
        *,
        role: MessageRole,
        content: str,
        agent: AgentName | None = None,
        message_id: str | None = None,
    ) -> Message:
        row = MessageRow(
            id=message_id or new_id("msg"),
            conversation_id=conversation_id,
            role=role,
            content=content,
            agent=agent,
        )
        self.session.add(row)
        await self.session.flush()
        return _to_message(row)

    async def update_status(
        self,
        conversation_id: str,
        status: ConversationStatus,
        *,
        resolution_outcome: ResolutionOutcome | None = None,
    ) -> Conversation:
        row = await self.session.get(ConversationRow, conversation_id)
        if row is None:
            raise NotFoundError(
                f"conversation {conversation_id} not found",
                details={"conversation_id": conversation_id},
            )
        row.status = status
        if resolution_outcome is not None:
            row.resolution_outcome = resolution_outcome
        await self.session.flush()
        return _to_conversation(row, include_messages=False)

    async def list_for_user(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[ConversationSummary], int]:
        condition = ConversationRow.user_id == user_id
        total = await self.session.scalar(
            select(func.count()).select_from(ConversationRow).where(condition)
        )
        stmt = (
            select(ConversationRow)
            .where(condition)
            .options(selectinload(ConversationRow.messages))
            .order_by(ConversationRow.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self.session.scalars(stmt)).all())
        summaries = [
            ConversationSummary(
                id=row.id,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                message_count=len(row.messages),
            )
            for row in rows
        ]
        return summaries, int(total or 0)
