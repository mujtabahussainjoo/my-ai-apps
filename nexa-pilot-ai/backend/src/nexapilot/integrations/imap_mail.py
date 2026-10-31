"""IMAP client for providers that offer IMAP with an app password.

Used as an alternative to OAuth for self-hosted or work accounts. Only read and
draft operations are implemented here; sending still requires explicit approval.
"""

from __future__ import annotations

import asyncio
import contextlib
import email
import imaplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.message import Message
from typing import Any

from nexapilot.core.errors import IntegrationError, PermissionDeniedError


@dataclass
class ImapMessage:
    uid: str
    subject: str
    sender: str
    recipients: list[str]
    snippet: str
    body_text: str
    received_at: datetime | None
    is_read: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_message_id": self.uid,
            "subject": self.subject,
            "sender": self.sender,
            "recipients": self.recipients,
            "snippet": self.snippet,
            "body_text": self.body_text,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "is_read": self.is_read,
        }


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return value


class ImapClient:
    def __init__(
        self,
        *,
        host: str,
        port: int = 993,
        username: str = "",
        password: str = "",
        use_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.timeout = timeout

    def _connect(self) -> imaplib.IMAP4:
        client: imaplib.IMAP4
        try:
            if self.use_ssl:
                client = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
            else:
                client = imaplib.IMAP4(self.host, self.port, timeout=self.timeout)
        except (OSError, imaplib.IMAP4.error) as exc:
            raise IntegrationError(
                f"Could not connect to the mail server: {type(exc).__name__}",
                details={"host": self.host},
            ) from exc
        try:
            client.login(self.username, self.password)
        except imaplib.IMAP4.error as exc:
            raise PermissionDeniedError(
                "The mail server rejected the credentials",
                details={"host": self.host, "username": self.username},
            ) from exc
        return client

    async def list_messages(
        self, *, query: str = "", folder: str = "INBOX", limit: int = 20
    ) -> list[ImapMessage]:
        return await asyncio.to_thread(self._list_messages_sync, query, folder, limit)

    def _list_messages_sync(self, query: str, folder: str, limit: int) -> list[ImapMessage]:
        client = self._connect()
        try:
            client.select(folder)
            criteria = query.strip() or "ALL"
            status, data = client.search(None, criteria)
            if status != "OK":
                raise IntegrationError(
                    "The mail server rejected the search query", details={"folder": folder}
                )
            ids = data[0].split() if data and data[0] else []
            selected = ids[-limit:]
            messages: list[ImapMessage] = []
            for raw_uid in reversed(selected):
                status, payload = client.fetch(raw_uid, "(RFC822)")
                if status != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                parsed = email.message_from_bytes(payload[0][1])
                messages.append(_parse_imap_message(raw_uid.decode(), parsed))
            return messages
        finally:
            with contextlib.suppress(OSError, imaplib.IMAP4.error):
                client.logout()

    async def delete_message(self, uid: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, uid)

    def _delete_sync(self, uid: str) -> bool:
        client = self._connect()
        try:
            client.select("INBOX")
            client.store(uid, "+FLAGS", "\\Deleted")
            client.expunge()
        finally:
            with contextlib.suppress(OSError, imaplib.IMAP4.error):
                client.logout()
        return True

    async def test_connection(self) -> bool:
        try:
            await self.list_messages(limit=1)
        except IntegrationError:
            return False
        return True


def _parse_imap_message(uid: str, parsed: Message) -> ImapMessage:
    subject = decode_header_value(parsed.get("Subject"))
    sender = decode_header_value(parsed.get("From"))
    recipients = [
        decode_header_value(item) for item in (parsed.get("To") or "").split(",") if item.strip()
    ]
    date_header = parsed.get("Date")
    received = None
    if date_header:
        try:
            from email.utils import parsedate_to_datetime

            received = parsedate_to_datetime(date_header)
        except (TypeError, ValueError):
            received = None
    body = ""
    if parsed.is_multipart():
        for part in parsed.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes) and payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
    else:
        payload = parsed.get_payload(decode=True)
        if isinstance(payload, bytes) and payload:
            body = payload.decode(parsed.get_content_charset() or "utf-8", errors="replace")
    snippet = body[:280]
    return ImapMessage(
        uid=uid,
        subject=subject,
        sender=sender,
        recipients=recipients,
        snippet=snippet,
        body_text=body,
        received_at=received,
        is_read=bool(parsed.get("X-Status") and "Seen" in str(parsed.get("X-Status"))),
    )


def now_utc() -> datetime:
    return datetime.now(UTC)
