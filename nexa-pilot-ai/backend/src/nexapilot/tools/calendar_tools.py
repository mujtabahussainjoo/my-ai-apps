"""Calendar tools.

Read tools call Google Calendar directly and mirror results into the local
unified view where it matters. Every write/watch tool is approval-gated in code
by :class:`~nexapilot.tools.base.ToolSpec`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from nexapilot.agents.permissions import CALENDAR_READ, CALENDAR_WRITE
from nexapilot.tools.base import Tool, ToolContext, ToolRisk, ToolSpec

_CALENDAR_WRITE = frozenset({CALENDAR_READ, CALENDAR_WRITE})
_CALENDAR_READ = frozenset({CALENDAR_READ})


class ListEventsInput(BaseModel):
    start: str = ""
    end: str = ""
    limit: int = Field(default=50, ge=1, le=200)


class SearchEventsInput(BaseModel):
    start: str = ""
    end: str = ""
    limit: int = Field(default=250, ge=1, le=2500)
    query: str = Field(default="", max_length=500)
    timezone: str = Field(default="", max_length=80)
    sync_token: str = Field(default="", max_length=4000)
    page_token: str = Field(default="", max_length=4000)
    single_events: bool = False
    order_by: str = Field(default="", max_length=40)
    show_deleted: bool = False
    updated_min: str = Field(default="", max_length=64)
    event_types: list[str] = Field(default_factory=list, max_length=10)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class ListEventsOutput(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    sources: dict[str, int] = Field(default_factory=dict)
    next_page_token: str = ""
    next_sync_token: str = ""


class GetEventInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=1024)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class EventOutput(BaseModel):
    event: dict[str, Any] = Field(default_factory=dict)


class EventListOutput(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    next_page_token: str = ""


class CreateEventInput(BaseModel):
    title: str = Field(min_length=1, max_length=400)
    start_at: str = Field(min_length=10, max_length=64)
    end_at: str = Field(min_length=10, max_length=64)
    description: str = Field(default="", max_length=5000)
    location: str = Field(default="", max_length=300)
    timezone: str = Field(default="UTC", max_length=80)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)
    attendees: list[str] = Field(default_factory=list, max_length=100)
    recurrence: list[str] = Field(default_factory=list, max_length=20)
    color_id: str = Field(default="", max_length=8)
    visibility: str = Field(default="", max_length=20)
    transparency: str = Field(default="", max_length=20)
    send_updates: str = Field(default="", max_length=20)


class CreateEventOutput(BaseModel):
    event_id: str = ""
    account_id: str = ""
    account_email: str = ""
    title: str = ""
    start_at: str = ""
    end_at: str = ""
    status: str = "created"


class UpdateEventInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=1024)
    body: dict[str, Any] = Field(min_length=1)
    send_updates: str = Field(default="", max_length=20)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class PatchEventInput(UpdateEventInput):
    pass


class DeleteEventInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=1024)
    send_updates: str = Field(default="", max_length=20)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class MoveEventInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=1024)
    destination: str = Field(min_length=1, max_length=300)
    send_updates: str = Field(default="", max_length=20)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class QuickAddEventInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    send_updates: str = Field(default="", max_length=20)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class ImportEventInput(BaseModel):
    body: dict[str, Any] = Field(min_length=1)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class ListInstancesInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=1024)
    limit: int = Field(default=250, ge=1, le=2500)
    page_token: str = Field(default="", max_length=4000)
    original_start: str = Field(default="", max_length=64)
    start: str = ""
    end: str = ""
    timezone: str = Field(default="", max_length=80)
    show_deleted: bool = False
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class ChannelInput(BaseModel):
    channel_id: str = Field(min_length=1, max_length=300)
    address: str = Field(min_length=8, max_length=1000, pattern=r"^https://")
    token: str = Field(default="", max_length=1000)
    expiration: str = Field(default="", max_length=32)
    params: dict[str, str] = Field(default_factory=dict)
    account_id: str = Field(default="", max_length=64)
    calendar_id: str = Field(default="primary", max_length=300)


class ChannelOutput(BaseModel):
    channel: dict[str, Any] = Field(default_factory=dict)


class FreebusyItem(BaseModel):
    calendar_id: str = Field(default="primary", max_length=300)


class FreebusyInput(BaseModel):
    items: list[FreebusyItem] = Field(default_factory=list, max_length=100)
    time_min: str = Field(min_length=10, max_length=64)
    time_max: str = Field(min_length=10, max_length=64)
    timezone: str = Field(default="UTC", max_length=80)
    group_expansion_max: int = Field(default=100, ge=1, le=100)
    calendar_expansion_max: int = Field(default=50, ge=1, le=100)
    account_id: str = Field(default="", max_length=64)


class FreebusyOutput(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class ColorsOutput(BaseModel):
    colors: dict[str, Any] = Field(default_factory=dict)


class ColorsInput(BaseModel):
    account_id: str = Field(default="", max_length=64)


class DeleteOutput(BaseModel):
    status: str = "deleted"
    event_id: str = ""
    account_id: str = ""


class ListEventsTool(Tool):
    spec = ToolSpec(
        name="list_events",
        purpose="List calendar events and events inferred from email, with their provenance.",
        input_model=ListEventsInput,
        output_model=ListEventsOutput,
        permissions=_CALENDAR_READ,
        side_effects=False,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ListEventsInput)
        from nexapilot.services.calendar_service import list_events

        start = _parse_dt(args.start) if args.start else None
        end = _parse_dt(args.end) if args.end else None
        events = list_events(ctx, start=start, end=end, limit=args.limit)
        sources: dict[str, int] = {}
        for event in events:
            source = str(event["source"])
            sources[source] = sources.get(source, 0) + 1
        return ListEventsOutput(events=events, count=len(events), sources=sources)


class SearchEventsTool(Tool):
    spec = ToolSpec(
        name="search_calendar_events",
        purpose="Query Google Calendar events with time, text, sync and page filters.",
        input_model=SearchEventsInput,
        output_model=ListEventsOutput,
        permissions=_CALENDAR_READ,
        side_effects=False,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, SearchEventsInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        events, next_sync, next_page = await client.list_events(
            sync_token=args.sync_token,
            time_min=_iso(args.start),
            time_max=_iso(args.end),
            max_results=args.limit,
            page_token=args.page_token,
            q=args.query,
            single_events=args.single_events,
            order_by=args.order_by,
            show_deleted=args.show_deleted,
            time_zone=args.timezone,
            updated_min=_iso(args.updated_min),
            event_types=args.event_types,
        )
        payloads = [event.to_dict() for event in events]
        sources: dict[str, int] = {}
        for event in events:
            sources[event.event_type] = sources.get(event.event_type, 0) + 1
        return ListEventsOutput(
            events=payloads,
            count=len(payloads),
            sources=sources,
            next_page_token=next_page,
            next_sync_token=next_sync,
        )


class GetEventTool(Tool):
    spec = ToolSpec(
        name="get_event",
        purpose="Fetch one Google Calendar event by its event ID.",
        input_model=GetEventInput,
        output_model=EventOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, GetEventInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        event = await client.get_event(args.event_id)
        return EventOutput(event=event.to_dict())


class ListInstancesTool(Tool):
    spec = ToolSpec(
        name="list_event_instances",
        purpose="List the instances of a recurring Google Calendar event.",
        input_model=ListInstancesInput,
        output_model=EventListOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ListInstancesInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        events, next_page = await client.list_event_instances(
            args.event_id,
            max_results=args.limit,
            page_token=args.page_token,
            original_start=_iso(args.original_start),
            time_min=_iso(args.start),
            time_max=_iso(args.end),
            time_zone=args.timezone,
            show_deleted=args.show_deleted,
        )
        payloads = [event.to_dict() for event in events]
        return EventListOutput(events=payloads, count=len(payloads), next_page_token=next_page)


class CreateEventTool(Tool):
    spec = ToolSpec(
        name="create_event",
        purpose="Create a calendar event. Requires explicit user approval first.",
        input_model=CreateEventInput,
        output_model=CreateEventOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=60.0,
        max_retries=0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.create_event",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, CreateEventInput)
        from nexapilot.core.errors import ValidationError
        from nexapilot.services.calendar_service import create_event

        start = _parse_dt(args.start_at)
        end = _parse_dt(args.end_at)
        if start is None or end is None:
            raise ValidationError("start_at and end_at must be ISO-8601 timestamps")
        if end <= start:
            raise ValidationError("end_at must be after start_at")
        result = await create_event(
            ctx,
            title=args.title,
            start_at=start,
            end_at=end,
            description=args.description,
            location=args.location,
            timezone=args.timezone,
            account_id=args.account_id,
            calendar_id=args.calendar_id,
            attendees=args.attendees,
            recurrence=args.recurrence,
            color_id=args.color_id,
            visibility=args.visibility,
            transparency=args.transparency,
            send_updates=args.send_updates,
        )
        return CreateEventOutput(**result)


class UpdateEventTool(Tool):
    spec = ToolSpec(
        name="update_event",
        purpose="Replace a calendar event. Requires explicit user approval first.",
        input_model=UpdateEventInput,
        output_model=EventOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=60.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.update_event",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, UpdateEventInput)
        from nexapilot.services.calendar_service import (
            calendar_client,
            store_calendar_event,
        )

        account, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        event = await client.update_event(args.event_id, args.body, send_updates=args.send_updates)
        store_calendar_event(ctx, account, event)
        ctx.session.flush()
        return EventOutput(event=event.to_dict())


class PatchEventTool(Tool):
    spec = ToolSpec(
        name="patch_event",
        purpose="Partially update a calendar event. Requires approval first.",
        input_model=PatchEventInput,
        output_model=EventOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=60.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.patch_event",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, PatchEventInput)
        from nexapilot.services.calendar_service import (
            calendar_client,
            store_calendar_event,
        )

        account, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        event = await client.patch_event(args.event_id, args.body, send_updates=args.send_updates)
        store_calendar_event(ctx, account, event)
        ctx.session.flush()
        return EventOutput(event=event.to_dict())


class DeleteEventTool(Tool):
    spec = ToolSpec(
        name="delete_event",
        purpose="Delete a calendar event. Requires explicit user approval first.",
        input_model=DeleteEventInput,
        output_model=DeleteOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.delete_event",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, DeleteEventInput)
        from nexapilot.services.calendar_service import (
            calendar_client,
            remove_calendar_event,
        )

        account, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        await client.delete_event(args.event_id, send_updates=args.send_updates)
        remove_calendar_event(ctx, account.id, args.event_id)
        ctx.session.flush()
        return DeleteOutput(event_id=args.event_id, account_id=account.id)


class MoveEventTool(Tool):
    spec = ToolSpec(
        name="move_event",
        purpose="Move an event to another calendar. Requires approval first.",
        input_model=MoveEventInput,
        output_model=EventOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=60.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.move_event",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, MoveEventInput)
        from nexapilot.services.calendar_service import (
            calendar_client,
            store_calendar_event,
        )

        account, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        event = await client.move_event(
            args.event_id, args.destination, send_updates=args.send_updates
        )
        store_calendar_event(ctx, account, event)
        ctx.session.flush()
        return EventOutput(event=event.to_dict())


class QuickAddEventTool(Tool):
    spec = ToolSpec(
        name="quick_add_event",
        purpose="Create an event from natural language. Requires approval first.",
        input_model=QuickAddEventInput,
        output_model=EventOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.quick_add_event",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, QuickAddEventInput)
        from nexapilot.services.calendar_service import (
            calendar_client,
            store_calendar_event,
        )

        account, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        event = await client.quick_add_event(args.text, send_updates=args.send_updates)
        store_calendar_event(ctx, account, event)
        ctx.session.flush()
        return EventOutput(event=event.to_dict())


class ImportEventTool(Tool):
    spec = ToolSpec(
        name="import_event",
        purpose="Import a private copy of an existing event. Requires approval first.",
        input_model=ImportEventInput,
        output_model=EventOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.import_event",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ImportEventInput)
        from nexapilot.services.calendar_service import (
            calendar_client,
            store_calendar_event,
        )

        account, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        event = await client.import_event(args.body)
        store_calendar_event(ctx, account, event)
        ctx.session.flush()
        return EventOutput(event=event.to_dict())


class WatchEventsTool(Tool):
    spec = ToolSpec(
        name="watch_events",
        purpose="Create a push channel for calendar event changes. Requires approval.",
        input_model=ChannelInput,
        output_model=ChannelOutput,
        permissions=_CALENDAR_READ,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.watch_events",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ChannelInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        client.calendar_id = args.calendar_id
        return ChannelOutput(channel=await client.watch_events(_channel_body(args)))


class QueryFreebusyTool(Tool):
    spec = ToolSpec(
        name="query_freebusy",
        purpose="Return free/busy information for a set of calendars.",
        input_model=FreebusyInput,
        output_model=FreebusyOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, FreebusyInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        items = [{"id": item.calendar_id} for item in args.items] or [{"id": "primary"}]
        result = await client.query_freebusy(
            {
                "timeMin": _iso(args.time_min),
                "timeMax": _iso(args.time_max),
                "timeZone": args.timezone,
                "groupExpansionMax": args.group_expansion_max,
                "calendarExpansionMax": args.calendar_expansion_max,
                "items": items,
            }
        )
        return FreebusyOutput(result=result)


class GetColorsTool(Tool):
    spec = ToolSpec(
        name="get_calendar_colors",
        purpose="Return the color definitions available for calendars and events.",
        input_model=ColorsInput,
        output_model=ColorsOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ColorsInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return ColorsOutput(colors=await client.get_colors())


def _channel_body(args: ChannelInput) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": args.channel_id,
        "type": "web_hook",
        "address": args.address,
    }
    if args.token:
        body["token"] = args.token
    if args.expiration:
        body["expiration"] = args.expiration
    if args.params:
        body["params"] = args.params
    return body


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _iso(value: str) -> str:
    parsed = _parse_dt(value)
    return parsed.isoformat() if parsed else value


def default_window(days: int = 7) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now, now + timedelta(days=days)
