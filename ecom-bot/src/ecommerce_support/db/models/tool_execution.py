"""Tool execution audit persistence (DATA-001 ``tool_executions``; SEC-010)."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import CreatedAtMixin, enum_column_type
from ecommerce_support.schemas.enums import ToolCallStatus


class ToolExecution(Base, CreatedAtMixin):
    """Audit record of one tool invocation (summary only; no raw secrets)."""

    __tablename__ = "tool_executions"
    __table_args__ = (Index("ix_tool_executions_conversation", "conversation_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ToolCallStatus] = mapped_column(
        enum_column_type(ToolCallStatus, "tool_call_status"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
