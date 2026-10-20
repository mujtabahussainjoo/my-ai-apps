"""Tool execution audit repository (SEC-010)."""

from __future__ import annotations

from sqlalchemy import select

from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import ToolExecution as ToolExecutionRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import ToolExecution
from ecommerce_support.schemas.enums import ToolCallStatus


def _to_execution(row: ToolExecutionRow) -> ToolExecution:
    return ToolExecution(
        call_id=row.call_id,
        tool_name=row.tool_name,
        status=row.status,
        summary=row.summary,
        duration_ms=row.duration_ms,
    )


class ToolExecutionRepository(BaseRepository):
    """Record tool invocations for audit and debugging (summaries only)."""

    async def record(
        self,
        *,
        tool_name: str,
        call_id: str,
        status: ToolCallStatus,
        conversation_id: str | None = None,
        message_id: str | None = None,
        summary: str = "",
        duration_ms: float | None = None,
        execution_id: str | None = None,
    ) -> ToolExecution:
        row = ToolExecutionRow(
            id=execution_id or new_id("tool"),
            conversation_id=conversation_id,
            message_id=message_id,
            tool_name=tool_name,
            call_id=call_id,
            status=status,
            summary=summary,
            duration_ms=duration_ms,
        )
        self.session.add(row)
        await self.session.flush()
        return _to_execution(row)

    async def list_for_conversation(
        self, conversation_id: str, *, limit: int = 100
    ) -> list[ToolExecution]:
        stmt = (
            select(ToolExecutionRow)
            .where(ToolExecutionRow.conversation_id == conversation_id)
            .order_by(ToolExecutionRow.created_at.asc())
            .limit(limit)
        )
        return [_to_execution(row) for row in (await self.session.scalars(stmt)).all()]

    async def list_by_message_ids(self, message_ids: list[str]) -> dict[str, list[ToolExecution]]:
        """Group tool executions by the assistant message they belong to (FR-002, FR-009)."""
        if not message_ids:
            return {}
        stmt = (
            select(ToolExecutionRow)
            .where(ToolExecutionRow.message_id.in_(message_ids))
            .order_by(ToolExecutionRow.created_at.asc())
        )
        grouped: dict[str, list[ToolExecution]] = {}
        for row in (await self.session.scalars(stmt)).all():
            if row.message_id is not None:
                grouped.setdefault(row.message_id, []).append(_to_execution(row))
        return grouped
