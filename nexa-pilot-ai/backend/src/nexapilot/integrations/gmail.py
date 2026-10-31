"""Gmail API client.

Only the scopes the user actually granted are used. Access tokens are refreshed
on demand; a revoked grant surfaces as an explicit error instead of a silent
re-login.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import httpx

from nexapilot.core.errors import PermissionDeniedError
from nexapilot.core.logging import get_logger
from nexapilot.providers.http import classify_status, wrap_transport_error

log = get_logger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class GmailMessage:
    id: str
    thread_id: str
    subject: str
    sender: str
    recipients: list[str]
    snippet: str
    body_text: str
    labels: list[str]
    received_at: datetime | None
    is_read: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_message_id": self.id,
            "thread_id": self.thread_id,
            "subject": self.subject,
            "sender": self.sender,
            "recipients": self.recipients,
            "snippet": self.snippet,
            "body_text": self.body_text,
            "labels": self.labels,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "is_read": self.is_read,
        }


class GmailClient:
    def __init__(
        self,
        access_token: str,
        *,
        timeout: float = 30.0,
        transport: Any = None,
    ) -> None:
        self._access_token = access_token
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self._access_token}"}

    async def _request(
        self, method: str, path: str, *, params: dict[str, str] | None = None, json_body: Any = None
    ) -> dict[str, Any]:
        url = f"{GMAIL_API}{path}"
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.request(
                    method, url, params=params, json=json_body, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "Gmail", self._timeout) from exc
            if response.status_code in (401, 403):
                raise PermissionDeniedError(
                    "Gmail rejected the stored grant. Reconnect the account to continue.",
                    details={"provider": "gmail", "status": response.status_code},
                )
            if response.status_code >= 400:
                raise classify_status(response.status_code, "Gmail", response.text)
            if not response.content:
                return {}
            payload: dict[str, Any] = response.json()
            return payload

    async def list_messages(
        self, *, query: str = "", max_results: int = 20, page_token: str = ""
    ) -> tuple[list[str], str]:
        params = {"maxResults": str(min(max_results, 100))}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        data = await self._request("GET", "/messages", params=params)
        ids = [str(item.get("id")) for item in data.get("messages") or [] if item.get("id")]
        return ids, str(data.get("nextPageToken") or "")

    async def get_message(self, message_id: str) -> GmailMessage:
        data = await self._request("GET", f"/messages/{message_id}", params={"format": "full"})
        return _parse_message(data)

    async def create_draft(self, *, to: list[str], subject: str, body: str) -> str:
        payload = {"message": {"raw": _encode_raw_message(to=to, subject=subject, body=body)}}
        data = await self._request("POST", "/drafts", json_body=payload)
        return str(data.get("id") or "")

    async def send_message(self, *, to: list[str], subject: str, body: str) -> str:
        payload = {"raw": _encode_raw_message(to=to, subject=subject, body=body)}
        data = await self._request("POST", "/messages/send", json_body=payload)
        return str(data.get("id") or "")

    async def delete_message(self, message_id: str) -> bool:
        """Move a message to the trash. Recoverable, unlike a permanent delete."""
        await self._request("POST", f"/messages/{message_id}/trash")
        return True


def _encode_raw_message(*, to: list[str], subject: str, body: str) -> str:
    """Gmail requires a base64url-encoded RFC 822 message."""
    message = EmailMessage()
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _parse_message(data: dict[str, Any]) -> GmailMessage:
    payload = data.get("payload") or {}
    headers = {
        str(header.get("name", "")).lower(): str(header.get("value", ""))
        for header in payload.get("headers") or []
        if isinstance(header, dict)
    }
    body_text = _extract_body(payload)
    received = None
    if headers.get("date"):
        try:
            from email.utils import parsedate_to_datetime

            received = parsedate_to_datetime(headers["date"])
        except (TypeError, ValueError):
            received = None
    labels = [str(label) for label in data.get("labelIds") or []]
    return GmailMessage(
        id=str(data.get("id") or ""),
        thread_id=str(data.get("threadId") or ""),
        subject=headers.get("subject", ""),
        sender=headers.get("from", ""),
        recipients=[item.strip() for item in headers.get("to", "").split(",") if item.strip()],
        snippet=str(data.get("snippet") or ""),
        body_text=body_text,
        labels=labels,
        received_at=received,
        is_read="UNREAD" not in labels,
    )


def _extract_body(payload: dict[str, Any]) -> str:
    mime = payload.get("mimeType") or ""
    if mime == "text/plain":
        data = (payload.get("body") or {}).get("data")
        if data:
            return _decode_base64(data)
    parts = payload.get("parts") or []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_mime = part.get("mimeType") or ""
        if part_mime == "text/plain":
            data = (part.get("body") or {}).get("data")
            if data:
                return _decode_base64(data)
        if part_mime.startswith("multipart/"):
            nested = _extract_body(part)
            if nested:
                return nested
    data = (payload.get("body") or {}).get("data")
    if data:
        text = _decode_base64(data)
        if mime.startswith("text/html"):
            text = _TAG_RE.sub(" ", text)
        return text
    return ""


def _decode_base64(value: str) -> str:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode(
            "utf-8", errors="replace"
        )
    except (ValueError, TypeError):
        return ""


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
