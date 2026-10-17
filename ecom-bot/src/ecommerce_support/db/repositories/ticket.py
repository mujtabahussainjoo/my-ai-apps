"""Support ticket repository with idempotent creation (FR-043, FR-044)."""

from __future__ import annotations

from sqlalchemy import select

from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import SupportTicket as TicketRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import Ticket, TicketRequest
from ecommerce_support.schemas.enums import Priority, TicketProvider, TicketStatus


def _to_ticket(row: TicketRow) -> Ticket:
    return Ticket(
        id=row.id,
        conversation_id=row.conversation_id,
        provider=row.provider,
        status=row.status,
        summary=row.summary,
        priority=row.priority,
        external_id=row.external_id,
        url=row.url,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class TicketRepository(BaseRepository):
    """Persist escalation tickets; ``create_idempotent`` prevents duplicates (FR-043)."""

    async def get(self, ticket_id: str) -> Ticket | None:
        row = await self.session.get(TicketRow, ticket_id)
        return _to_ticket(row) if row is not None else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> Ticket | None:
        row = await self.session.scalar(
            select(TicketRow).where(TicketRow.idempotency_key == idempotency_key)
        )
        return _to_ticket(row) if row is not None else None

    async def list_by_conversation(self, conversation_id: str) -> list[Ticket]:
        stmt = (
            select(TicketRow)
            .where(TicketRow.conversation_id == conversation_id)
            .order_by(TicketRow.created_at.asc())
        )
        return [_to_ticket(row) for row in (await self.session.scalars(stmt)).all()]

    async def create_idempotent(
        self,
        request: TicketRequest,
        *,
        provider: TicketProvider,
        status: TicketStatus,
        external_id: str | None = None,
        url: str | None = None,
    ) -> tuple[Ticket, bool]:
        """Return ``(ticket, created)``. A repeat with the same idempotency key returns the
        existing ticket with ``created=False`` (no duplicate)."""
        if request.idempotency_key is not None:
            existing = await self.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                return existing, False

        row = TicketRow(
            id=new_id("tkt"),
            conversation_id=request.conversation_id,
            provider=provider,
            status=status,
            summary=request.summary,
            priority=request.priority,
            external_id=external_id,
            url=url,
            idempotency_key=request.idempotency_key,
            description=request.description or None,
            request_payload=request.model_dump(mode="json"),
        )
        self.session.add(row)
        await self.session.flush()
        return _to_ticket(row), True

    async def update(
        self,
        ticket_id: str,
        *,
        status: TicketStatus | None = None,
        external_id: str | None = None,
        url: str | None = None,
        priority: Priority | None = None,
    ) -> Ticket | None:
        row = await self.session.get(TicketRow, ticket_id)
        if row is None:
            return None
        if status is not None:
            row.status = status
        if external_id is not None:
            row.external_id = external_id
        if url is not None:
            row.url = url
        if priority is not None:
            row.priority = priority
        await self.session.flush()
        return _to_ticket(row)
