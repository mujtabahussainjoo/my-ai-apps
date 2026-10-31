"""Google Calendar API v3 client.

Covers the resource surface documented at
https://developers.google.com/workspace/calendar/api/v3/reference:
Acl, CalendarList, Calendars, Channels, Colors, Events, Freebusy and Settings.

The client is intentionally stateless. Account selection, token handling and the
local unified-event cache live in ``services/calendar_service.py``; the approval
gate lives in the tool layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from nexapilot.core.errors import PermissionDeniedError, ProviderError
from nexapilot.providers.http import classify_status, wrap_transport_error

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"


@dataclass
class CalendarEvent:
    id: str
    summary: str
    description: str = ""
    location: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None
    timezone: str = "UTC"
    all_day: bool = False
    status: str = "confirmed"
    etag: str = ""
    html_link: str = ""
    recurring_event_id: str = ""
    event_type: str = "default"
    raw: dict[str, Any] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "external_id": self.id,
            "title": self.summary,
            "description": self.description,
            "location": self.location,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "timezone": self.timezone,
            "all_day": self.all_day,
            "status": self.status,
            "etag": self.etag,
            "html_link": self.html_link,
            "recurring_event_id": self.recurring_event_id,
            "event_type": self.event_type,
        }


def _clean_params(params: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            cleaned[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple, set)):
            items = [str(item) for item in value if str(item)]
            if items:
                cleaned[key] = ",".join(items)
        else:
            cleaned[key] = str(value)
    return cleaned


def _calendar_path(calendar_id: str, suffix: str = "") -> str:
    encoded = quote(calendar_id or "primary", safe="@")
    if suffix:
        return f"/calendars/{encoded}/{suffix}"
    return f"/calendars/{encoded}"


def _segment(value: str) -> str:
    return quote(value, safe="")


def _calendar_list_path(calendar_id: str) -> str:
    encoded = quote(calendar_id or "primary", safe="@")
    return f"/users/me/calendarList/{encoded}"


class GoogleCalendarClient:
    def __init__(
        self,
        access_token: str,
        *,
        calendar_id: str = "primary",
        timeout: float = 30.0,
        transport: Any = None,
    ) -> None:
        self._access_token = access_token
        self.calendar_id = calendar_id
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._access_token}"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        url = f"{CALENDAR_API}{path}"
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.request(
                    method, url, params=params, json=json_body, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "Google Calendar", self._timeout) from exc
            if response.status_code in (401, 403):
                raise PermissionDeniedError(
                    "Google Calendar rejected the stored grant. Reconnect the account.",
                    details={"provider": "google_calendar", "status": response.status_code},
                )
            if response.status_code >= 400:
                raise classify_status(response.status_code, "Google Calendar", response.text)
            if not response.content:
                return {}
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError("Google Calendar returned a non-JSON response") from exc
            if not isinstance(payload, dict):
                raise ProviderError("Google Calendar returned an unexpected payload shape")
            return payload

    # Events ----------------------------------------------------------------
    async def list_events(
        self,
        *,
        sync_token: str = "",
        time_min: str = "",
        time_max: str = "",
        max_results: int = 250,
        page_token: str = "",
        q: str = "",
        single_events: bool = False,
        order_by: str = "",
        show_deleted: bool = False,
        time_zone: str = "",
        updated_min: str = "",
        i_cal_uid: str = "",
        event_types: list[str] | None = None,
        max_attendees: int | None = None,
        always_include_email: bool = False,
        private_extended_property: list[str] | None = None,
        shared_extended_property: list[str] | None = None,
    ) -> tuple[list[CalendarEvent], str, str]:
        params = _clean_params(
            {
                "maxResults": min(max(max_results, 1), 2500),
                "syncToken": sync_token,
                "timeMin": time_min,
                "timeMax": time_max,
                "pageToken": page_token,
                "q": q,
                "singleEvents": single_events,
                "orderBy": order_by,
                "showDeleted": show_deleted,
                "timeZone": time_zone,
                "updatedMin": updated_min,
                "iCalUID": i_cal_uid,
                "eventTypes": event_types or [],
                "maxAttendees": max_attendees,
                "alwaysIncludeEmail": always_include_email,
                "privateExtendedProperty": private_extended_property or [],
                "sharedExtendedProperty": shared_extended_property or [],
            }
        )
        data = await self._request("GET", _calendar_path(self.calendar_id, "events"), params=params)
        events = [_parse_event(item) for item in data.get("items") or [] if isinstance(item, dict)]
        return (
            events,
            str(data.get("nextSyncToken") or ""),
            str(data.get("nextPageToken") or ""),
        )

    async def get_event(self, event_id: str) -> CalendarEvent:
        data = await self._request(
            "GET", _calendar_path(self.calendar_id, f"events/{_segment(event_id)}")
        )
        return _parse_event(data)

    async def create_event(
        self,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        description: str = "",
        location: str = "",
        timezone: str = "UTC",
        attendees: list[str] | None = None,
        recurrence: list[str] | None = None,
        color_id: str = "",
        visibility: str = "",
        transparency: str = "",
        send_updates: str = "",
    ) -> CalendarEvent:
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": email} for email in attendees]
        if recurrence:
            body["recurrence"] = recurrence
        if color_id:
            body["colorId"] = color_id
        if visibility:
            body["visibility"] = visibility
        if transparency:
            body["transparency"] = transparency
        return await self.insert_event(body, send_updates=send_updates)

    async def insert_event(self, body: dict[str, Any], *, send_updates: str = "") -> CalendarEvent:
        params = _clean_params({"sendUpdates": send_updates})
        data = await self._request(
            "POST",
            _calendar_path(self.calendar_id, "events"),
            params=params,
            json_body=body,
        )
        return _parse_event(data)

    async def import_event(self, body: dict[str, Any]) -> CalendarEvent:
        data = await self._request(
            "POST",
            _calendar_path(self.calendar_id, "events/import"),
            json_body=body,
        )
        return _parse_event(data)

    async def update_event(
        self, event_id: str, body: dict[str, Any], *, send_updates: str = ""
    ) -> CalendarEvent:
        params = _clean_params({"sendUpdates": send_updates})
        data = await self._request(
            "PUT",
            _calendar_path(self.calendar_id, f"events/{_segment(event_id)}"),
            params=params,
            json_body=body,
        )
        return _parse_event(data)

    async def patch_event(
        self, event_id: str, body: dict[str, Any], *, send_updates: str = ""
    ) -> CalendarEvent:
        params = _clean_params({"sendUpdates": send_updates})
        data = await self._request(
            "PATCH",
            _calendar_path(self.calendar_id, f"events/{_segment(event_id)}"),
            params=params,
            json_body=body,
        )
        return _parse_event(data)

    async def delete_event(self, event_id: str, *, send_updates: str = "") -> dict[str, Any]:
        params = _clean_params({"sendUpdates": send_updates})
        return await self._request(
            "DELETE",
            _calendar_path(self.calendar_id, f"events/{_segment(event_id)}"),
            params=params,
        )

    async def move_event(
        self, event_id: str, destination: str, *, send_updates: str = ""
    ) -> CalendarEvent:
        params = _clean_params({"destination": destination, "sendUpdates": send_updates})
        data = await self._request(
            "POST",
            _calendar_path(self.calendar_id, f"events/{_segment(event_id)}/move"),
            params=params,
        )
        return _parse_event(data)

    async def quick_add_event(self, text: str, *, send_updates: str = "") -> CalendarEvent:
        params = _clean_params({"text": text, "sendUpdates": send_updates})
        data = await self._request(
            "POST",
            _calendar_path(self.calendar_id, "events/quickAdd"),
            params=params,
        )
        return _parse_event(data)

    async def list_event_instances(
        self,
        event_id: str,
        *,
        max_results: int = 250,
        page_token: str = "",
        original_start: str = "",
        time_min: str = "",
        time_max: str = "",
        time_zone: str = "",
        show_deleted: bool = False,
        max_attendees: int | None = None,
    ) -> tuple[list[CalendarEvent], str]:
        params = _clean_params(
            {
                "maxResults": min(max(max_results, 1), 2500),
                "pageToken": page_token,
                "originalStart": original_start,
                "timeMin": time_min,
                "timeMax": time_max,
                "timeZone": time_zone,
                "showDeleted": show_deleted,
                "maxAttendees": max_attendees,
            }
        )
        data = await self._request(
            "GET",
            _calendar_path(self.calendar_id, f"events/{_segment(event_id)}/instances"),
            params=params,
        )
        instances = [
            _parse_event(item) for item in data.get("items") or [] if isinstance(item, dict)
        ]
        return instances, str(data.get("nextPageToken") or "")

    async def watch_events(self, channel: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            _calendar_path(self.calendar_id, "events/watch"),
            json_body=channel,
        )

    # CalendarList ----------------------------------------------------------
    async def list_calendar_list(
        self,
        *,
        max_results: int = 250,
        page_token: str = "",
        min_access_role: str = "",
        show_deleted: bool = False,
        show_hidden: bool = False,
        sync_token: str = "",
    ) -> dict[str, Any]:
        params = _clean_params(
            {
                "maxResults": min(max(max_results, 1), 250),
                "pageToken": page_token,
                "minAccessRole": min_access_role,
                "showDeleted": show_deleted,
                "showHidden": show_hidden,
                "syncToken": sync_token,
            }
        )
        return await self._request("GET", "/users/me/calendarList", params=params)

    async def get_calendar_list_entry(self, calendar_id: str) -> dict[str, Any]:
        return await self._request("GET", _calendar_list_path(calendar_id))

    async def insert_calendar_list_entry(
        self, body: dict[str, Any], *, color_rgb_format: bool = False
    ) -> dict[str, Any]:
        params = _clean_params({"colorRgbFormat": color_rgb_format})
        return await self._request("POST", "/users/me/calendarList", params=params, json_body=body)

    async def update_calendar_list_entry(
        self, calendar_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request("PUT", _calendar_list_path(calendar_id), json_body=body)

    async def patch_calendar_list_entry(
        self, calendar_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._request("PATCH", _calendar_list_path(calendar_id), json_body=body)

    async def delete_calendar_list_entry(self, calendar_id: str) -> dict[str, Any]:
        return await self._request("DELETE", _calendar_list_path(calendar_id))

    async def watch_calendar_list(self, channel: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/users/me/calendarList/watch", json_body=channel)

    # Calendars -------------------------------------------------------------
    async def get_calendar(self, calendar_id: str) -> dict[str, Any]:
        return await self._request("GET", _calendar_path(calendar_id))

    async def insert_calendar(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/calendars", json_body=body)

    async def update_calendar(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", _calendar_path(calendar_id), json_body=body)

    async def patch_calendar(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PATCH", _calendar_path(calendar_id), json_body=body)

    async def delete_calendar(self, calendar_id: str) -> dict[str, Any]:
        return await self._request("DELETE", _calendar_path(calendar_id))

    async def clear_calendar(self, calendar_id: str) -> dict[str, Any]:
        return await self._request("POST", _calendar_path(calendar_id, "clear"))

    async def transfer_calendar_ownership(
        self,
        calendar_id: str,
        *,
        new_data_owner: str,
        use_admin_access: bool = True,
    ) -> dict[str, Any]:
        params = _clean_params({"newDataOwner": new_data_owner, "useAdminAccess": use_admin_access})
        return await self._request(
            "POST", _calendar_path(calendar_id, "transferOwnership"), params=params
        )

    # Acl -------------------------------------------------------------------
    async def list_acl(
        self,
        *,
        calendar_id: str = "",
        max_results: int = 100,
        page_token: str = "",
        show_deleted: bool = False,
        sync_token: str = "",
    ) -> dict[str, Any]:
        params = _clean_params(
            {
                "maxResults": min(max(max_results, 1), 100),
                "pageToken": page_token,
                "showDeleted": show_deleted,
                "syncToken": sync_token,
            }
        )
        return await self._request(
            "GET", _calendar_path(calendar_id or self.calendar_id, "acl"), params=params
        )

    async def get_acl_rule(self, rule_id: str, *, calendar_id: str = "") -> dict[str, Any]:
        return await self._request(
            "GET",
            _calendar_path(calendar_id or self.calendar_id, f"acl/{_segment(rule_id)}"),
        )

    async def insert_acl_rule(
        self,
        body: dict[str, Any],
        *,
        calendar_id: str = "",
        send_notifications: bool = False,
    ) -> dict[str, Any]:
        params = _clean_params({"sendNotifications": send_notifications})
        return await self._request(
            "POST",
            _calendar_path(calendar_id or self.calendar_id, "acl"),
            params=params,
            json_body=body,
        )

    async def update_acl_rule(
        self, rule_id: str, body: dict[str, Any], *, calendar_id: str = ""
    ) -> dict[str, Any]:
        return await self._request(
            "PUT",
            _calendar_path(calendar_id or self.calendar_id, f"acl/{_segment(rule_id)}"),
            json_body=body,
        )

    async def patch_acl_rule(
        self, rule_id: str, body: dict[str, Any], *, calendar_id: str = ""
    ) -> dict[str, Any]:
        return await self._request(
            "PATCH",
            _calendar_path(calendar_id or self.calendar_id, f"acl/{_segment(rule_id)}"),
            json_body=body,
        )

    async def delete_acl_rule(self, rule_id: str, *, calendar_id: str = "") -> dict[str, Any]:
        return await self._request(
            "DELETE",
            _calendar_path(calendar_id or self.calendar_id, f"acl/{_segment(rule_id)}"),
        )

    async def watch_acl(self, channel: dict[str, Any], *, calendar_id: str = "") -> dict[str, Any]:
        return await self._request(
            "POST",
            _calendar_path(calendar_id or self.calendar_id, "acl/watch"),
            json_body=channel,
        )

    # Colors / Freebusy / Settings / Channels --------------------------------
    async def get_colors(self) -> dict[str, Any]:
        return await self._request("GET", "/colors")

    async def query_freebusy(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/freeBusy", json_body=body)

    async def list_settings(
        self,
        *,
        max_results: int = 100,
        page_token: str = "",
        sync_token: str = "",
    ) -> dict[str, Any]:
        params = _clean_params(
            {
                "maxResults": min(max(max_results, 1), 250),
                "pageToken": page_token,
                "syncToken": sync_token,
            }
        )
        return await self._request("GET", "/users/me/settings", params=params)

    async def get_setting(self, setting: str) -> dict[str, Any]:
        return await self._request("GET", f"/users/me/settings/{_segment(setting)}")

    async def watch_settings(self, channel: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/users/me/settings/watch", json_body=channel)

    async def stop_channel(self, channel_id: str, resource_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/channels/stop",
            json_body={"id": channel_id, "resourceId": resource_id},
        )


def _parse_event(item: dict[str, Any]) -> CalendarEvent:
    start = item.get("start") or {}
    end = item.get("end") or {}
    return CalendarEvent(
        id=str(item.get("id") or ""),
        summary=str(item.get("summary") or ""),
        description=str(item.get("description") or ""),
        location=str(item.get("location") or ""),
        start_at=_parse_dt(start),
        end_at=_parse_dt(end),
        timezone=str(start.get("timeZone") or "UTC"),
        all_day=bool(start.get("date")),
        status=str(item.get("status") or "confirmed"),
        etag=str(item.get("etag") or ""),
        html_link=str(item.get("htmlLink") or ""),
        recurring_event_id=str(item.get("recurringEventId") or ""),
        event_type=str(item.get("eventType") or "default"),
        raw=item,
    )


def _parse_dt(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("dateTime") or payload.get("date")
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
