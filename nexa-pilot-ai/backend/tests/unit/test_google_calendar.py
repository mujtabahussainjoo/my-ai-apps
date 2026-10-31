"""Google Calendar v3 client tests. All HTTP is mocked with ``httpx.MockTransport``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from nexapilot.core.errors import PermissionDeniedError
from nexapilot.integrations.google_calendar import GoogleCalendarClient

BASE = "https://www.googleapis.com/calendar/v3"


def _event(event_id: str = "evt-1") -> dict[str, Any]:
    return {
        "id": event_id,
        "summary": "Standup",
        "description": "Daily sync",
        "location": "Room 1",
        "start": {"dateTime": "2026-10-29T09:00:00Z", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-29T09:15:00Z", "timeZone": "UTC"},
        "status": "confirmed",
        "etag": '"etag-1"',
        "htmlLink": "https://calendar.google.com/event?eid=evt-1",
        "eventType": "default",
    }


@pytest.fixture
def recorder() -> list[httpx.Request]:
    return []


def _client(
    recorder: list[httpx.Request],
    payload: dict[str, Any] | None = None,
    *,
    status: int = 200,
) -> GoogleCalendarClient:
    body = payload if payload is not None else _event()

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        if request.method == "DELETE" or request.url.path.endswith("/clear"):
            return httpx.Response(204)
        return httpx.Response(status, json=body)

    return GoogleCalendarClient(
        "token", calendar_id="primary", transport=httpx.MockTransport(handler)
    )


async def test_event_crud_paths_and_payloads(recorder: list[httpx.Request]) -> None:
    client = _client(recorder)
    start = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
    end = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)

    created = await client.create_event(
        summary="Standup",
        start=start,
        end=end,
        attendees=["a@example.com"],
        recurrence=["RRULE:FREQ=DAILY"],
        send_updates="all",
    )
    assert created.id == "evt-1"
    assert created.html_link.endswith("evt-1")
    create_request = recorder[-1]
    assert create_request.method == "POST"
    assert create_request.url.path == "/calendar/v3/calendars/primary/events"
    assert create_request.url.params["sendUpdates"] == "all"
    body = json.loads(create_request.content)
    assert body["attendees"] == [{"email": "a@example.com"}]
    assert body["recurrence"] == ["RRULE:FREQ=DAILY"]

    await client.get_event("evt-1")
    assert recorder[-1].method == "GET"
    assert recorder[-1].url.path.endswith("/events/evt-1")

    await client.update_event("evt-1", {"summary": "Updated"})
    assert recorder[-1].method == "PUT"

    await client.patch_event("evt-1", {"summary": "Patched"})
    assert recorder[-1].method == "PATCH"

    await client.delete_event("evt-1")
    assert recorder[-1].method == "DELETE"

    await client.move_event("evt-1", "team@example.com")
    assert recorder[-1].method == "POST"
    assert recorder[-1].url.path.endswith("/events/evt-1/move")
    assert recorder[-1].url.params["destination"] == "team@example.com"

    await client.quick_add_event("Lunch tomorrow at noon")
    assert recorder[-1].url.path.endswith("/events/quickAdd")
    assert recorder[-1].url.params["text"] == "Lunch tomorrow at noon"

    await client.import_event(_event())
    assert recorder[-1].url.path.endswith("/events/import")


async def test_list_events_and_instances_map_tokens(recorder: list[httpx.Request]) -> None:
    payload = {
        "items": [_event()],
        "nextSyncToken": "sync-2",
        "nextPageToken": "page-2",
    }
    client = _client(recorder, payload)
    events, next_sync, next_page = await client.list_events(
        sync_token="sync-1",
        max_results=5000,
        single_events=True,
        order_by="startTime",
    )
    assert len(events) == 1
    assert events[0].event_type == "default"
    assert (next_sync, next_page) == ("sync-2", "page-2")
    params = recorder[-1].url.params
    assert params["maxResults"] == "2500"
    assert params["singleEvents"] == "true"
    assert params["syncToken"] == "sync-1"

    instances, next_instance_page = await client.list_event_instances("evt-1")
    assert len(instances) == 1
    assert next_instance_page == "page-2"
    assert recorder[-1].url.path.endswith("/events/evt-1/instances")


async def test_calendar_list_acl_settings_colors_and_channels(
    recorder: list[httpx.Request],
) -> None:
    client = _client(recorder)

    await client.list_calendar_list(show_hidden=True)
    assert recorder[-1].url.path == "/calendar/v3/users/me/calendarList"
    assert recorder[-1].url.params["showHidden"] == "true"

    await client.get_calendar_list_entry("primary")
    assert recorder[-1].url.path == "/calendar/v3/users/me/calendarList/primary"

    await client.insert_calendar_list_entry({"id": "primary"})
    assert recorder[-1].method == "POST"

    await client.update_calendar_list_entry("primary", {"colorId": "1"})
    assert recorder[-1].method == "PUT"

    await client.patch_calendar_list_entry("primary", {"colorId": "2"})
    assert recorder[-1].method == "PATCH"

    await client.delete_calendar_list_entry("primary")
    assert recorder[-1].method == "DELETE"

    await client.list_acl(calendar_id="primary", show_deleted=True)
    assert recorder[-1].url.path == "/calendar/v3/calendars/primary/acl"

    await client.get_acl_rule("user:a@example.com", calendar_id="primary")
    assert recorder[-1].url.raw_path.decode().endswith("/acl/user%3Aa%40example.com")

    await client.insert_acl_rule({"role": "reader"}, calendar_id="primary", send_notifications=True)
    assert recorder[-1].url.params["sendNotifications"] == "true"

    await client.update_acl_rule("user:a@example.com", {"role": "writer"})
    assert recorder[-1].method == "PUT"

    await client.patch_acl_rule("user:a@example.com", {"role": "reader"})
    assert recorder[-1].method == "PATCH"

    await client.delete_acl_rule("user:a@example.com")
    assert recorder[-1].method == "DELETE"

    channel = {"id": "channel-1", "type": "web_hook", "address": "https://example.test"}
    await client.watch_events(channel)
    assert recorder[-1].url.path == "/calendar/v3/calendars/primary/events/watch"
    await client.watch_acl(channel, calendar_id="primary")
    assert recorder[-1].url.path == "/calendar/v3/calendars/primary/acl/watch"
    await client.watch_calendar_list(channel)
    assert recorder[-1].url.path == "/calendar/v3/users/me/calendarList/watch"
    await client.watch_settings(channel)
    assert recorder[-1].url.path == "/calendar/v3/users/me/settings/watch"

    await client.stop_channel("channel-1", "resource-1")
    assert recorder[-1].url.path == "/calendar/v3/channels/stop"
    assert json.loads(recorder[-1].content) == {
        "id": "channel-1",
        "resourceId": "resource-1",
    }

    await client.get_colors()
    assert recorder[-1].url.path == "/calendar/v3/colors"

    await client.query_freebusy({"items": [{"id": "primary"}]})
    assert recorder[-1].url.path == "/calendar/v3/freeBusy"

    await client.list_settings()
    assert recorder[-1].url.path == "/calendar/v3/users/me/settings"

    await client.get_setting("timezone")
    assert recorder[-1].url.path.endswith("/settings/timezone")


async def test_calendar_metadata_and_ownership(recorder: list[httpx.Request]) -> None:
    client = _client(recorder)

    await client.get_calendar("team@example.com")
    assert recorder[-1].url.path == "/calendar/v3/calendars/team@example.com"

    await client.insert_calendar({"summary": "Team"})
    assert recorder[-1].url.path == "/calendar/v3/calendars"

    await client.update_calendar("team@example.com", {"summary": "Team 2"})
    assert recorder[-1].method == "PUT"

    await client.patch_calendar("team@example.com", {"summary": "Team 3"})
    assert recorder[-1].method == "PATCH"

    await client.clear_calendar("primary")
    assert recorder[-1].url.path == "/calendar/v3/calendars/primary/clear"

    await client.delete_calendar("team@example.com")
    assert recorder[-1].method == "DELETE"

    await client.transfer_calendar_ownership("team@example.com", new_data_owner="new@example.com")
    assert recorder[-1].url.path.endswith("/transferOwnership")
    assert recorder[-1].url.params["newDataOwner"] == "new@example.com"
    assert recorder[-1].url.params["useAdminAccess"] == "true"


async def test_rejected_grant_is_normalized(recorder: list[httpx.Request]) -> None:
    client = _client(recorder, status=403)
    with pytest.raises(PermissionDeniedError):
        await client.get_event("evt-1")
