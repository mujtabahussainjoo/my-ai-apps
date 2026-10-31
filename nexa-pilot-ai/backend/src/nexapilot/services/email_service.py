"""Email service: account synchronisation, drafts and sending."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select

from nexapilot.core.errors import (
    ExternalServiceNotConfiguredError,
    IntegrationError,
    NotFoundError,
    PermissionDeniedError,
)
from nexapilot.core.logging import get_logger
from nexapilot.db.models import AuditLog, ConnectedAccount, EmailMessage
from nexapilot.integrations.gmail import GmailClient, GmailMessage
from nexapilot.integrations.imap_mail import ImapClient
from nexapilot.integrations.oauth import OAuthTokens, account_secret_reference
from nexapilot.tools.base import ToolContext

log = get_logger(__name__)


class MailAccountClient(Protocol):
    async def list_messages(self, *, query: str = "", limit: int = 20) -> list[dict[str, Any]]: ...

    async def send_message(self, *, to: list[str], subject: str, body: str) -> str: ...

    async def create_draft(self, *, to: list[str], subject: str, body: str) -> str: ...

    async def delete_message(self, message_id: str) -> bool: ...


def _account_tokens(ctx: ToolContext, account: ConnectedAccount) -> OAuthTokens:
    reference = account_secret_reference(account.id, "tokens")
    raw = ctx.container.secrets.get(reference)
    if not raw:
        raise PermissionDeniedError(
            "The stored credentials for this account are missing. Reconnect the account.",
            details={"account_id": account.id},
        )
    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PermissionDeniedError(
            "The stored credentials for this account are unreadable. Reconnect the account.",
            details={"account_id": account.id},
        ) from exc
    return OAuthTokens.from_dict(payload)


def _store_tokens(ctx: ToolContext, account_id: str, tokens: OAuthTokens) -> None:
    import json

    reference = account_secret_reference(account_id, "tokens")
    ctx.container.secrets.set(reference, json.dumps(tokens.to_dict()))


async def _refresh_if_needed(ctx: ToolContext, account: ConnectedAccount) -> OAuthTokens:
    tokens = _account_tokens(ctx, account)
    if not tokens.is_expired():
        return tokens
    client_id = ctx.container.secrets.get("google:oauth:client_id") or ""
    client_secret = ctx.container.secrets.get("google:oauth:client_secret") or ""
    if not client_id or not client_secret or not tokens.refresh_token:
        raise PermissionDeniedError(
            "The account grant has expired and cannot be refreshed. Reconnect the account.",
            details={"account_id": account.id},
        )
    from nexapilot.integrations.oauth import refresh_tokens

    refreshed = await refresh_tokens(
        client_id=client_id, client_secret=client_secret, refresh_token=tokens.refresh_token
    )
    _store_tokens(ctx, account.id, refreshed)
    return refreshed


def build_mail_client(ctx: ToolContext, account: ConnectedAccount) -> MailAccountClient:
    if account.provider == "gmail":
        tokens = _account_tokens(ctx, account)
        return GmailAccountClient(account, tokens)
    if account.provider == "imap":
        extra = account.extra or {}
        return ImapAccountClient(
            host=str(extra.get("host") or ""),
            port=int(extra.get("port") or 993),
            username=str(extra.get("username") or account.email),
            password=ctx.container.secrets.get(account_secret_reference(account.id, "password"))
            or "",
            smtp_host=str(extra.get("smtp_host") or ""),
            smtp_port=int(extra.get("smtp_port") or 587),
            smtp_use_ssl=bool(extra.get("smtp_use_ssl")),
        )
    raise ExternalServiceNotConfiguredError(
        f"Unsupported mail provider '{account.provider}'",
        setup_hint="Reconnect the account using a supported provider.",
    )


class GmailAccountClient:
    def __init__(self, account: ConnectedAccount, tokens: OAuthTokens) -> None:
        self._account = account
        self._tokens = tokens

    def _client(self) -> GmailClient:
        return GmailClient(self._tokens.access_token)

    async def list_messages(self, *, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        client = self._client()
        ids, _ = await client.list_messages(query=query, max_results=limit)
        messages: list[dict[str, Any]] = []
        for message_id in ids:
            message: GmailMessage = await client.get_message(message_id)
            messages.append(message.to_dict())
        return messages

    async def send_message(self, *, to: list[str], subject: str, body: str) -> str:
        return await self._client().send_message(to=to, subject=subject, body=body)

    async def create_draft(self, *, to: list[str], subject: str, body: str) -> str:
        return await self._client().create_draft(to=to, subject=subject, body=body)

    async def delete_message(self, message_id: str) -> bool:
        return await self._client().delete_message(message_id)


class ImapAccountClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        timeout: float = 30.0,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_use_ssl: bool = False,
    ) -> None:
        self._client = ImapClient(
            host=host, port=port, username=username, password=password, timeout=timeout
        )
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._smtp_use_ssl = smtp_use_ssl
        self._username = username
        self._password = password

    async def list_messages(self, *, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        messages = await self._client.list_messages(query=query, limit=limit)
        return [message.to_dict() for message in messages]

    async def send_message(self, *, to: list[str], subject: str, body: str) -> str:
        if not self._smtp_host:
            raise NotImplementedError(
                "This IMAP account has no SMTP server configured. Add one to enable sending."
            )
        from nexapilot.integrations.smtp_mail import SmtpClient

        smtp = SmtpClient(
            host=self._smtp_host,
            port=self._smtp_port,
            username=self._username,
            password=self._password,
            use_ssl=self._smtp_use_ssl,
        )
        return await smtp.send_message(to=to, subject=subject, body=body)

    async def create_draft(self, *, to: list[str], subject: str, body: str) -> str:
        # IMAP has no portable drafts API; the draft is stored locally by the service.
        raise NotImplementedError("Drafts for IMAP accounts are stored locally.")

    async def delete_message(self, message_id: str) -> bool:
        return await self._client.delete_message(message_id)


async def sync_account(
    ctx: ToolContext, account: ConnectedAccount, *, limit: int = 50
) -> dict[str, Any]:
    """Pull new messages for an account into the local store."""
    client: MailAccountClient
    if account.provider == "gmail":
        tokens = await _refresh_if_needed(ctx, account)
        client = GmailAccountClient(account, tokens)
    else:
        client = build_mail_client(ctx, account)

    payloads = await client.list_messages(limit=limit)
    existing = {
        row.provider_message_id
        for row in ctx.session.scalars(
            select(EmailMessage).where(EmailMessage.account_id == account.id)
        )
    }
    imported = 0
    for payload in payloads:
        message_id = str(payload.get("provider_message_id") or "")
        if not message_id or message_id in existing:
            continue
        received = payload.get("received_at")
        message = EmailMessage(
            account_id=account.id,
            provider_message_id=message_id,
            thread_id=str(payload.get("thread_id") or ""),
            subject=str(payload.get("subject") or ""),
            sender=str(payload.get("sender") or ""),
            recipients=list(payload.get("recipients") or []),
            snippet=str(payload.get("snippet") or ""),
            body_text=str(payload.get("body_text") or ""),
            folder="INBOX",
            labels=list(payload.get("labels") or []),
            is_read=bool(payload.get("is_read")),
            received_at=_parse_dt(received),
        )
        ctx.session.add(message)
        imported += 1
    account.last_sync_at = datetime.now(UTC)
    ctx.session.flush()
    return {"account_id": account.id, "imported": imported, "seen": len(payloads)}


async def create_draft(
    ctx: ToolContext, *, account_id: str, to: list[str], subject: str, body: str
) -> dict[str, Any]:
    """Create a draft. Drafts are local until the user approves sending."""
    account = _get_account(ctx, account_id)
    draft_id = ""
    try:
        client = build_mail_client(ctx, account)
        draft_id = await client.create_draft(to=to, subject=subject, body=body)
    except NotImplementedError:
        draft_id = ""

    message = EmailMessage(
        account_id=account.id,
        provider_message_id=draft_id or f"local-draft-{datetime.now(UTC).timestamp()}",
        subject=subject,
        sender=account.email,
        recipients=list(to),
        body_text=body,
        snippet=body[:280],
        folder="DRAFT",
        labels=["DRAFT"],
    )
    ctx.session.add(message)
    ctx.session.flush()
    _audit(ctx, "email.draft_created", target=account.email, details={"subject": subject[:120]})
    return {
        "draft_id": message.id,
        "account_id": account.id,
        "account_email": account.email,
        "status": "created",
        "subject": subject,
        "recipients": list(to),
    }


async def send_message(
    ctx: ToolContext, *, account_id: str, to: list[str], subject: str, body: str
) -> dict[str, Any]:
    """Send an email. The approval gate has already run before this is called."""
    account = _get_account(ctx, account_id)
    client = build_mail_client(ctx, account)
    try:
        provider_message_id = await client.send_message(to=to, subject=subject, body=body)
    except NotImplementedError as exc:
        raise IntegrationError(str(exc), details={"account_id": account.id}) from exc

    message = EmailMessage(
        account_id=account.id,
        provider_message_id=provider_message_id,
        subject=subject,
        sender=account.email,
        recipients=list(to),
        body_text=body,
        snippet=body[:280],
        folder="SENT",
        labels=["SENT"],
        received_at=datetime.now(UTC),
    )
    ctx.session.add(message)
    ctx.session.flush()
    _audit(
        ctx,
        "email.sent",
        target=account.email,
        details={"recipients": list(to), "subject": subject[:120]},
    )
    return {
        "provider_message_id": provider_message_id,
        "account_id": account.id,
        "account_email": account.email,
        "status": "sent",
    }


async def delete_message(ctx: ToolContext, *, message_id: str) -> dict[str, Any]:
    """Delete (trash) a message. The approval gate has already run."""
    message = ctx.session.get(EmailMessage, message_id)
    if message is None:
        from nexapilot.core.errors import NotFoundError

        raise NotFoundError(f"Email message '{message_id}' not found")
    account = _get_account(ctx, message.account_id)
    client = build_mail_client(ctx, account)
    try:
        await client.delete_message(message.provider_message_id)
    except NotImplementedError as exc:
        raise IntegrationError(str(exc), details={"account_id": account.id}) from exc
    ctx.session.delete(message)
    ctx.session.flush()
    _audit(
        ctx,
        "email.deleted",
        target=account.email,
        details={
            "subject": message.subject[:120],
            "provider_message_id": message.provider_message_id,
        },
    )
    return {"message_id": message_id, "account_id": account.id, "status": "deleted"}


async def forward_message(
    ctx: ToolContext, *, message_id: str, to: list[str], note: str = ""
) -> dict[str, Any]:
    """Forward a message. The approval gate has already run."""
    message = ctx.session.get(EmailMessage, message_id)
    if message is None:
        from nexapilot.core.errors import NotFoundError

        raise NotFoundError(f"Email message '{message_id}' not found")
    quoted = (
        f"{note}\n\n---------- Forwarded message ----------\n"
        f"From: {message.sender}\nSubject: {message.subject}\n\n{message.body_text}"
    )
    subject = (
        message.subject if message.subject.lower().startswith("fwd:") else f"Fwd: {message.subject}"
    )
    return await send_message(
        ctx,
        account_id=message.account_id,
        to=to,
        subject=subject,
        body=quoted,
    )


def _get_account(ctx: ToolContext, account_id: str) -> ConnectedAccount:
    accounts = list(
        ctx.session.scalars(select(ConnectedAccount).where(ConnectedAccount.status == "connected"))
    )
    if not accounts:
        raise ExternalServiceNotConfiguredError(
            "No email account is connected.",
            setup_hint="Connect an email account in Settings → Connected accounts.",
        )
    if account_id:
        for account in accounts:
            if account.id == account_id:
                return account
        raise NotFoundError(f"Account '{account_id}' is not connected")
    return accounts[0]


def _audit(
    ctx: ToolContext, action: str, *, target: str = "", details: dict[str, Any] | None = None
) -> None:
    entry = AuditLog(
        actor="agent", action=action, target=target[:300], status="ok", details=details or {}
    )
    ctx.session.add(entry)


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
