"""Audit event repository (SEC-010)."""

from __future__ import annotations

from sqlalchemy import select

from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import AuditEvent as AuditRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import AuditEvent, AuditEventCreate


def _to_event(row: AuditRow) -> AuditEvent:
    return AuditEvent(
        id=row.id,
        event_type=row.event_type,
        actor_id=row.actor_id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        conversation_id=row.conversation_id,
        detail=dict(row.detail),
        created_at=row.created_at,
    )


class AuditEventRepository(BaseRepository):
    """Append-only audit log. Callers must pass redacted detail (SEC-010)."""

    async def record(self, event: AuditEventCreate) -> AuditEvent:
        row = AuditRow(
            id=new_id("aud"),
            event_type=event.event_type,
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            conversation_id=event.conversation_id,
            detail=dict(event.detail),
        )
        self.session.add(row)
        await self.session.flush()
        return _to_event(row)

    async def list_for_conversation(
        self, conversation_id: str, *, limit: int = 100
    ) -> list[AuditEvent]:
        stmt = (
            select(AuditRow)
            .where(AuditRow.conversation_id == conversation_id)
            .order_by(AuditRow.created_at.asc())
            .limit(limit)
        )
        return [_to_event(row) for row in (await self.session.scalars(stmt)).all()]
