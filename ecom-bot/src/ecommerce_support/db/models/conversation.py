"""Conversation and message persistence (DATA-001 ``conversations``, ``messages``)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import CreatedAtMixin, TimestampMixin, enum_column_type
from ecommerce_support.schemas.enums import (
    AgentName,
    ConversationStatus,
    MessageRole,
    ResolutionOutcome,
)


class Conversation(Base, TimestampMixin):
    """A support conversation, optionally owned by a user (guests allowed).

    ``tenant_id`` keeps single-tenant default now with multi-store readiness (DATA-005).
    """

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_tenant_status", "tenant_id", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default", server_default="default", index=True
    )
    status: Mapped[ConversationStatus] = mapped_column(
        enum_column_type(ConversationStatus, "conversation_status"),
        nullable=False,
        default=ConversationStatus.OPEN,
        index=True,
    )
    resolution_outcome: Mapped[ResolutionOutcome | None] = mapped_column(
        enum_column_type(ResolutionOutcome, "resolution_outcome"), nullable=True
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="selectin",
    )


class Message(Base, CreatedAtMixin):
    """A single persisted message (user/assistant/tool/system)."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        enum_column_type(MessageRole, "message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent: Mapped[AgentName | None] = mapped_column(
        enum_column_type(AgentName, "agent_name"), nullable=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
