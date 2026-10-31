"""Unified calendar service.

Merges events from connected calendars with events inferred from authorised
email. Every event keeps its provenance and confidence so the UI can tell a real
calendar entry from an inferred one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from nexapilot.core.errors import ExternalServiceNotConfiguredError, NotFoundError
from nexapilot.core.logging import get_logger
from nexapilot.db.models import AuditLog, CalendarEvent, ConnectedAccount, EmailMessage
from nexapilot.integrations.event_extraction import extract_events
from nexapilot.integrations.google_calendar import (
    CalendarEvent as GoogleCalendarEvent,
)
from nexapilot.integrations.google_calendar import GoogleCalendarClient
from nexapilot.integrations.oauth import OAuthTokens, account_secret_reference
from nexapilot.tools.base import ToolContext

log = get_logger(__name__)


def _calendar_accounts(ctx: ToolContext) -> list[ConnectedAccount]:
    return list(
        ctx.session.scalars(
            select(ConnectedAccount).where(
                ConnectedAccount.provider.in_(["google_calendar", "gmail"]),
                ConnectedAccount.status == "connected",
            )
        )
    )


def _tokens_for(ctx: ToolContext, account: ConnectedAccount) -> OAuthTokens | None:
    import json

    raw = ctx.container.secrets.get(account_secret_reference(account.id, "tokens"))
    if not raw:
        return None
    try:
        return OAuthTokens.from_dict(json.loads(raw))
    except json.JSONDecodeError:
        return None


def calendar_client(
    ctx: ToolContext, account_id: str = ""
) -> tuple[ConnectedAccount, GoogleCalendarClient]:
    """Resolve the single calendar account used for a call and its API client."""
    accounts = _calendar_accounts(ctx)
    if account_id:
        accounts = [account for account in accounts if account.id == account_id]
    if not accounts:
        raise ExternalServiceNotConfiguredError(
            "No calendar is connected, so the request could not be sent.",
            setup_hint="Connect a Google account in Settings → Connected accounts.",
        )
    account = accounts[0]
    tokens = _tokens_for(ctx, account)
    if tokens is None:
        raise ExternalServiceNotConfiguredError(
            "This calendar account is not authorized.",
            setup_hint="Reconnect the account in Settings → Connected accounts.",
        )
    if tokens.is_expired():
        raise ExternalServiceNotConfiguredError(
            "The calendar grant has expired and must be renewed.",
            setup_hint="Reconnect the account in Settings → Connected accounts.",
        )
    return account, GoogleCalendarClient(tokens.access_token)


def store_calendar_event(
    ctx: ToolContext, account: ConnectedAccount, event: GoogleCalendarEvent
) -> None:
    """Insert or update the local unified-view copy of a Google event."""
    if not event.id:
        return
    dedupe = f"gcal:{event.id}"
    existing = ctx.session.scalars(
        select(CalendarEvent).where(
            CalendarEvent.account_id == account.id,
            CalendarEvent.source == "calendar",
            CalendarEvent.dedupe_key == dedupe,
        )
    ).first()
    cancelled = event.status == "cancelled"
    if existing is not None:
        existing.cancelled = cancelled
        existing.status = event.status
        existing.title = event.summary
        existing.start_at = event.start_at
        existing.end_at = event.end_at
        existing.timezone = event.timezone
        existing.description = event.description
        existing.location = event.location
        existing.all_day = event.all_day
        return
    ctx.session.add(
        CalendarEvent(
            account_id=account.id,
            source="calendar",
            external_id=event.id,
            title=event.summary,
            description=event.description,
            location=event.location,
            start_at=event.start_at,
            end_at=event.end_at,
            timezone=event.timezone,
            all_day=event.all_day,
            status=event.status,
            provenance=f"google_calendar:{account.id}",
            confidence=1.0,
            dedupe_key=dedupe,
            cancelled=cancelled,
        )
    )


def remove_calendar_event(ctx: ToolContext, account_id: str, event_id: str) -> None:
    existing = ctx.session.scalars(
        select(CalendarEvent).where(
            CalendarEvent.account_id == account_id,
            CalendarEvent.source == "calendar",
            CalendarEvent.dedupe_key == f"gcal:{event_id}",
        )
    ).first()
    if existing is not None:
        existing.cancelled = True
        existing.status = "cancelled"


def clear_calendar_events(ctx: ToolContext, account_id: str) -> int:
    rows = list(
        ctx.session.scalars(
            select(CalendarEvent).where(
                CalendarEvent.account_id == account_id,
                CalendarEvent.source == "calendar",
                CalendarEvent.cancelled.is_(False),
            )
        )
    )
    for row in rows:
        row.cancelled = True
        row.status = "cancelled"
    return len(rows)


async def sync_calendar(ctx: ToolContext, account: ConnectedAccount) -> dict[str, Any]:
    """Incremental sync using the stored sync token."""
    tokens = _tokens_for(ctx, account)
    if tokens is None:
        raise ExternalServiceNotConfiguredError(
            "This calendar account is not authorized.",
            setup_hint="Reconnect the account in Settings → Connected accounts.",
        )
    if tokens.is_expired():
        raise ExternalServiceNotConfiguredError(
            "The calendar grant has expired and must be renewed.",
            setup_hint="Reconnect the account in Settings → Connected accounts.",
        )
    client = GoogleCalendarClient(tokens.access_token)
    events, next_sync, _ = await client.list_events(sync_token=account.sync_cursor or "")
    imported = 0
    for event in events:
        existed = ctx.session.scalars(
            select(CalendarEvent).where(
                CalendarEvent.account_id == account.id,
                CalendarEvent.source == "calendar",
                CalendarEvent.dedupe_key == f"gcal:{event.id}",
            )
        ).first()
        store_calendar_event(ctx, account, event)
        if existed is None:
            imported += 1
    if next_sync:
        account.sync_cursor = next_sync
    account.last_sync_at = datetime.now(UTC)
    ctx.session.flush()
    return {"account_id": account.id, "imported": imported, "sync_token_set": bool(next_sync)}


async def extract_events_from_emails(
    ctx: ToolContext, account_id: str = "", *, limit: int = 100
) -> dict[str, Any]:
    """Infer events from authorised email and store them with provenance."""
    accounts = _calendar_accounts(ctx)
    if account_id:
        accounts = [account for account in accounts if account.id == account_id]
    if not accounts:
        raise ExternalServiceNotConfiguredError(
            "No connected account is available to read email from.",
            setup_hint="Connect an email account in Settings → Connected accounts.",
        )

    created = 0
    for account in accounts:
        messages = list(
            ctx.session.scalars(
                select(EmailMessage)
                .where(EmailMessage.account_id == account.id)
                .order_by(EmailMessage.received_at.desc())
                .limit(limit)
            )
        )
        for message in messages:
            extracted = extract_events(
                subject=message.subject,
                body=message.body_text,
                source_message_id=message.id,
                sender=message.sender,
                received_at=message.received_at,
            )
            for event in extracted:
                dedupe = event.dedupe_key
                exists = ctx.session.scalars(
                    select(CalendarEvent).where(
                        CalendarEvent.account_id == account.id,
                        CalendarEvent.source == "email",
                        CalendarEvent.dedupe_key == dedupe,
                    )
                ).first()
                if exists is not None:
                    continue
                ctx.session.add(
                    CalendarEvent(
                        account_id=account.id,
                        source="email",
                        external_id=message.id,
                        title=event.title,
                        description=message.snippet[:500],
                        start_at=event.start_at,
                        end_at=event.end_at,
                        timezone="UTC",
                        status="tentative",
                        provenance=event.provenance,
                        confidence=event.confidence,
                        dedupe_key=dedupe,
                    )
                )
                created += 1
    ctx.session.flush()
    return {"events_created": created}


def list_events(
    ctx: ToolContext,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(CalendarEvent).order_by(CalendarEvent.start_at.asc()).limit(limit)
    if start is not None:
        stmt = stmt.where(CalendarEvent.start_at >= start)
    if end is not None:
        stmt = stmt.where(CalendarEvent.start_at <= end)
    rows = list(ctx.session.scalars(stmt))
    return [
        {
            "id": row.id,
            "account_id": row.account_id,
            "source": row.source,
            "title": row.title,
            "description": row.description,
            "location": row.location,
            "start_at": row.start_at.isoformat() if row.start_at else None,
            "end_at": row.end_at.isoformat() if row.end_at else None,
            "timezone": row.timezone,
            "all_day": row.all_day,
            "status": row.status,
            "provenance": row.provenance,
            "confidence": row.confidence,
            "cancelled": row.cancelled,
        }
        for row in rows
    ]


async def create_event(
    ctx: ToolContext,
    *,
    title: str,
    start_at: datetime,
    end_at: datetime,
    description: str = "",
    location: str = "",
    timezone: str = "UTC",
    account_id: str = "",
    calendar_id: str = "primary",
    attendees: list[str] | None = None,
    recurrence: list[str] | None = None,
    color_id: str = "",
    visibility: str = "",
    transparency: str = "",
    send_updates: str = "",
) -> dict[str, Any]:
    """Create an event in the connected calendar and in the local unified view."""
    account, client = calendar_client(ctx, account_id)
    client.calendar_id = calendar_id
    event = await client.create_event(
        summary=title,
        start=start_at,
        end=end_at,
        description=description,
        location=location,
        timezone=timezone,
        attendees=attendees,
        recurrence=recurrence,
        color_id=color_id,
        visibility=visibility,
        transparency=transparency,
        send_updates=send_updates,
    )
    store_calendar_event(ctx, account, event)
    ctx.session.add(
        AuditLog(
            actor="agent",
            action="calendar.event_created",
            target=account.email,
            status="ok",
            details={"title": title[:120], "start_at": start_at.isoformat()},
        )
    )
    ctx.session.flush()
    return {
        "event_id": event.id,
        "account_id": account.id,
        "account_email": account.email,
        "title": event.summary,
        "start_at": event.start_at.isoformat() if event.start_at else None,
        "end_at": event.end_at.isoformat() if event.end_at else None,
        "status": "created",
    }


def find_conflicts(ctx: ToolContext, *, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Return events that overlap the given window."""
    rows = list(
        ctx.session.scalars(
            select(CalendarEvent).where(
                CalendarEvent.start_at.is_not(None),
                CalendarEvent.start_at < end,
                CalendarEvent.end_at.is_not(None),
                CalendarEvent.end_at > start,
                CalendarEvent.cancelled.is_(False),
            )
        )
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "start_at": row.start_at.isoformat() if row.start_at else None,
            "end_at": row.end_at.isoformat() if row.end_at else None,
            "source": row.source,
        }
        for row in rows
    ]


def upcoming_reminders(
    ctx: ToolContext, *, within: timedelta = timedelta(hours=24)
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    rows = list(
        ctx.session.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.start_at.is_not(None),
                CalendarEvent.start_at >= now,
                CalendarEvent.start_at <= now + within,
                CalendarEvent.cancelled.is_(False),
            )
            .order_by(CalendarEvent.start_at.asc())
        )
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "start_at": row.start_at.isoformat() if row.start_at else None,
            "source": row.source,
            "confidence": row.confidence,
        }
        for row in rows
    ]


def _require_account(ctx: ToolContext, account_id: str) -> ConnectedAccount:
    account = ctx.session.get(ConnectedAccount, account_id)
    if account is None:
        raise NotFoundError(f"Account '{account_id}' not found")
    return account
