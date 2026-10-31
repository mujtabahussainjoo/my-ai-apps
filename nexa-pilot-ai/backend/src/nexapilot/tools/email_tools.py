"""Email tools.

Reading is scoped to the accounts the user connected. Sending, forwarding and
deleting always require an explicit approval, enforced by the approval gate in
the agent loop and by the tool spec.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from nexapilot.agents.permissions import EMAIL_MODIFY, EMAIL_READ, EMAIL_SEND
from nexapilot.db.models import ConnectedAccount, EmailMessage
from nexapilot.tools.base import Tool, ToolContext, ToolRisk, ToolSpec


class EmailSearchInput(BaseModel):
    query: str = Field(default="", max_length=500)
    account_id: str = Field(default="", max_length=64)
    limit: int = Field(default=20, ge=1, le=50)


class EmailSearchOutput(BaseModel):
    account_id: str = ""
    account_email: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class EmailReadInput(BaseModel):
    message_id: str = Field(min_length=1, max_length=64)


class EmailReadOutput(BaseModel):
    message: dict[str, Any] = Field(default_factory=dict)


class EmailDraftInput(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=100_000)
    account_id: str = Field(default="", max_length=64)


class EmailDraftOutput(BaseModel):
    draft_id: str = ""
    account_id: str = ""
    account_email: str = ""
    status: str = "created"
    subject: str = ""
    recipients: list[str] = Field(default_factory=list)


class EmailSendInput(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=100_000)
    account_id: str = Field(default="", max_length=64)


class EmailSendOutput(BaseModel):
    provider_message_id: str = ""
    account_id: str = ""
    account_email: str = ""
    status: str = "sent"


def _accounts(ctx: ToolContext) -> list[ConnectedAccount]:
    return list(
        ctx.session.scalars(select(ConnectedAccount).where(ConnectedAccount.status == "connected"))
    )


def _pick_account(ctx: ToolContext, account_id: str) -> ConnectedAccount:
    accounts = _accounts(ctx)
    if not accounts:
        from nexapilot.core.errors import ExternalServiceNotConfiguredError

        raise ExternalServiceNotConfiguredError(
            "No email account is connected.",
            setup_hint="Connect an email account in Settings → Connected accounts.",
        )
    if account_id:
        for account in accounts:
            if account.id == account_id:
                return account
        from nexapilot.core.errors import NotFoundError

        raise NotFoundError(f"Account '{account_id}' is not connected")
    return accounts[0]


def _matches(message: EmailMessage, query: str) -> bool:
    if not query:
        return True
    needle = query.lower()
    return (
        needle in message.subject.lower()
        or needle in message.sender.lower()
        or needle in message.snippet.lower()
        or needle in message.body_text.lower()
    )


class SearchEmailTool(Tool):
    spec = ToolSpec(
        name="search_email",
        purpose="Search the messages of a connected email account.",
        input_model=EmailSearchInput,
        output_model=EmailSearchOutput,
        permissions=frozenset({EMAIL_READ}),
        side_effects=False,
        timeout_seconds=60.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, EmailSearchInput)
        account = _pick_account(ctx, args.account_id)
        messages = list(
            ctx.session.scalars(
                select(EmailMessage)
                .where(EmailMessage.account_id == account.id)
                .order_by(EmailMessage.received_at.desc())
                .limit(500)
            )
        )
        selected = [message for message in messages if _matches(message, args.query)][: args.limit]
        return EmailSearchOutput(
            account_id=account.id,
            account_email=account.email,
            count=len(selected),
            messages=[
                {
                    "id": message.id,
                    "subject": message.subject,
                    "sender": message.sender,
                    "snippet": message.snippet[:300],
                    "received_at": message.received_at.isoformat() if message.received_at else None,
                    "is_read": message.is_read,
                    "folder": message.folder,
                }
                for message in selected
            ],
        )


class ReadEmailTool(Tool):
    spec = ToolSpec(
        name="read_email",
        purpose="Read the full content of one email message.",
        input_model=EmailReadInput,
        output_model=EmailReadOutput,
        permissions=frozenset({EMAIL_READ}),
        side_effects=False,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, EmailReadInput)
        message = ctx.session.get(EmailMessage, args.message_id)
        if message is None:
            from nexapilot.core.errors import NotFoundError

            raise NotFoundError(f"Email message '{args.message_id}' not found")
        return EmailReadOutput(
            message={
                "id": message.id,
                "account_id": message.account_id,
                "subject": message.subject,
                "sender": message.sender,
                "recipients": message.recipients,
                "body_text": message.body_text[:50_000],
                "received_at": message.received_at.isoformat() if message.received_at else None,
            }
        )


class CreateDraftTool(Tool):
    spec = ToolSpec(
        name="create_draft",
        purpose="Create an email draft. The draft is not sent until it is approved.",
        input_model=EmailDraftInput,
        output_model=EmailDraftOutput,
        permissions=frozenset({EMAIL_READ, EMAIL_MODIFY}),
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=False,
        audit=True,
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, EmailDraftInput)
        from nexapilot.services.email_service import create_draft

        result = await create_draft(
            ctx,
            account_id=args.account_id,
            to=args.to,
            subject=args.subject,
            body=args.body,
        )
        return EmailDraftOutput(**result)


class SendEmailTool(Tool):
    spec = ToolSpec(
        name="send_email",
        purpose="Send an email message. Requires explicit user approval first.",
        input_model=EmailSendInput,
        output_model=EmailSendOutput,
        permissions=frozenset({EMAIL_READ, EMAIL_SEND}),
        side_effects=True,
        timeout_seconds=60.0,
        max_retries=0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="email.send",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, EmailSendInput)
        from nexapilot.services.email_service import send_message

        result = await send_message(
            ctx,
            account_id=args.account_id,
            to=args.to,
            subject=args.subject,
            body=args.body,
        )
        return EmailSendOutput(**result)


class EmailDeleteInput(BaseModel):
    message_id: str = Field(min_length=1, max_length=64)


class EmailDeleteOutput(BaseModel):
    message_id: str = ""
    account_id: str = ""
    status: str = "deleted"


class EmailForwardInput(BaseModel):
    message_id: str = Field(min_length=1, max_length=64)
    to: list[str] = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=5000)


class EmailForwardOutput(BaseModel):
    provider_message_id: str = ""
    account_id: str = ""
    account_email: str = ""
    status: str = "sent"


class DeleteEmailTool(Tool):
    spec = ToolSpec(
        name="delete_email",
        purpose="Move an email message to the trash. Requires explicit user approval first.",
        input_model=EmailDeleteInput,
        output_model=EmailDeleteOutput,
        permissions=frozenset({EMAIL_READ, EMAIL_MODIFY}),
        side_effects=True,
        timeout_seconds=60.0,
        max_retries=0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="email.delete",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, EmailDeleteInput)
        from nexapilot.services.email_service import delete_message

        result = await delete_message(ctx, message_id=args.message_id)
        return EmailDeleteOutput(**result)


class ForwardEmailTool(Tool):
    spec = ToolSpec(
        name="forward_email",
        purpose="Forward an email message. Requires explicit user approval first.",
        input_model=EmailForwardInput,
        output_model=EmailForwardOutput,
        permissions=frozenset({EMAIL_READ, EMAIL_SEND}),
        side_effects=True,
        timeout_seconds=60.0,
        max_retries=0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="email.forward",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, EmailForwardInput)
        from nexapilot.services.email_service import forward_message

        result = await forward_message(ctx, message_id=args.message_id, to=args.to, note=args.note)
        return EmailForwardOutput(**result)
