"""Connected account routes: OAuth start/callback, IMAP accounts, disconnect."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexapilot.api.deps import ContainerDep, SessionDep
from nexapilot.core.container import Container
from nexapilot.core.errors import (
    ExternalServiceNotConfiguredError,
    NotFoundError,
    ValidationError,
)
from nexapilot.db.models import ConnectedAccount, EmailMessage

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class ImapAccountRequest(BaseModel):
    email: str = Field(min_length=3, max_length=300)
    password: str = Field(min_length=1, max_length=500)
    host: str = Field(min_length=3, max_length=200)
    port: int = Field(default=993, ge=1, le=65535)
    label: str = Field(default="", max_length=200)
    smtp_host: str = Field(default="", max_length=200)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_use_ssl: bool = False


class AccountSchema(BaseModel):
    id: str
    provider: str
    email: str = ""
    label: str = ""
    status: str = "connected"
    scopes: list[str] = Field(default_factory=list)
    auth_mode: str = ""
    last_sync_at: str | None = None
    error: str = ""


@router.get("", response_model=list[AccountSchema])
def list_accounts(session: Session = SessionDep) -> list[AccountSchema]:
    rows = list(session.scalars(select(ConnectedAccount).order_by(ConnectedAccount.created_at)))
    return [
        AccountSchema(
            id=row.id,
            provider=row.provider,
            email=row.email,
            label=row.label,
            status=row.status,
            scopes=list(row.scopes or []),
            auth_mode=row.auth_mode,
            last_sync_at=row.last_sync_at.isoformat() if row.last_sync_at else None,
            error=row.error,
        )
        for row in rows
    ]


@router.get("/oauth/google/start")
async def start_google_oauth(
    request: Request, container: Container = ContainerDep
) -> dict[str, Any]:
    """Return the Google authorisation URL for the requested scopes."""
    import secrets

    client_id = container.secrets.get("google:oauth:client_id") or ""
    if not client_id:
        raise ExternalServiceNotConfiguredError(
            "No Google OAuth client is configured.",
            setup_hint=(
                "Create an OAuth client in Google Cloud Console and store the client id "
                "and secret in Settings → Connected accounts."
            ),
        )
    scopes = request.query_params.get("scopes", "gmail")
    scope_list = _scopes_for(scopes)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    request.app.state.oauth_states[state] = {"verifier": verifier, "scopes": scope_list}

    from nexapilot.integrations.oauth import build_authorization_url

    url = build_authorization_url(
        client_id=client_id,
        redirect_uri=container.settings.google_oauth_redirect_uri,
        scopes=scope_list,
        state=state,
        code_verifier=verifier,
    )
    return {"authorization_url": url, "state": state, "scopes": scope_list}


@router.post("/oauth/google/callback")
async def google_oauth_callback(
    request: Request, container: Container = ContainerDep, session: Session = SessionDep
) -> dict[str, Any]:
    params = dict(request.query_params)
    code = params.get("code")
    state = params.get("state")
    if not code or not state:
        raise ValidationError("Missing OAuth code or state")
    pending = request.app.state.oauth_states.pop(state, None)
    if pending is None:
        raise ValidationError("Unknown or expired OAuth state")

    client_id = container.secrets.get("google:oauth:client_id") or ""
    client_secret = container.secrets.get("google:oauth:client_secret") or ""
    if not client_id or not client_secret:
        raise ExternalServiceNotConfiguredError("Google OAuth client is not configured.")

    from nexapilot.integrations.oauth import account_secret_reference, exchange_code

    tokens = await exchange_code(
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=container.settings.google_oauth_redirect_uri,
        code_verifier=pending["verifier"],
    )

    account = ConnectedAccount(
        provider="gmail",
        account_id="gmail",
        label="Gmail",
        email="",
        auth_mode="oauth",
        scopes=list(tokens.scopes or pending["scopes"]),
        status="connected",
    )
    session.add(account)
    session.flush()
    import json

    container.secrets.set(
        account_secret_reference(account.id, "tokens"), json.dumps(tokens.to_dict())
    )
    session.commit()
    return {"account_id": account.id, "status": "connected", "scopes": account.scopes}


@router.post("/imap", response_model=AccountSchema)
async def connect_imap_account(
    payload: ImapAccountRequest,
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> AccountSchema:
    from nexapilot.integrations.imap_mail import ImapClient
    from nexapilot.integrations.oauth import account_secret_reference

    client = ImapClient(
        host=payload.host,
        port=payload.port,
        username=payload.email,
        password=payload.password,
    )
    try:
        await client.list_messages(limit=1)
    except Exception as exc:
        raise ValidationError(f"Could not verify the mail account: {exc}") from exc

    account = ConnectedAccount(
        provider="imap",
        account_id=payload.email,
        label=payload.label or payload.email,
        email=payload.email,
        auth_mode="password",
        scopes=["imap:read"],
        status="connected",
        extra={
            "host": payload.host,
            "port": payload.port,
            "username": payload.email,
            "smtp_host": payload.smtp_host,
            "smtp_port": payload.smtp_port,
            "smtp_use_ssl": payload.smtp_use_ssl,
        },
    )
    session.add(account)
    session.flush()
    container.secrets.set(account_secret_reference(account.id, "password"), payload.password)
    session.commit()
    return AccountSchema(
        id=account.id,
        provider=account.provider,
        email=account.email,
        label=account.label,
        status=account.status,
        scopes=list(account.scopes or []),
        auth_mode=account.auth_mode,
    )


@router.delete("/{account_id}")
def disconnect_account(
    account_id: str, container: Container = ContainerDep, session: Session = SessionDep
) -> dict[str, Any]:
    from nexapilot.integrations.oauth import account_secret_reference

    account = session.get(ConnectedAccount, account_id)
    if account is None:
        raise NotFoundError(f"Account '{account_id}' not found")
    for kind in ("tokens", "password"):
        container.secrets.delete(account_secret_reference(account.id, kind))
    stored = list(
        session.scalars(select(EmailMessage).where(EmailMessage.account_id == account.id))
    )
    for message in stored:
        session.delete(message)
    session.delete(account)
    session.commit()
    return {"status": "disconnected", "deleted_local_messages": len(stored)}


@router.post("/{account_id}/sync")
async def sync_account(
    account_id: str, container: Container = ContainerDep, session: Session = SessionDep
) -> dict[str, Any]:
    from nexapilot.services.email_service import sync_account as run_sync
    from nexapilot.tools.base import ToolContext

    account = session.get(ConnectedAccount, account_id)
    if account is None:
        raise NotFoundError(f"Account '{account_id}' not found")
    ctx = ToolContext(container=container, session=session)
    result = await run_sync(ctx, account)
    session.commit()
    return result


def _scopes_for(kind: str) -> list[str]:
    from nexapilot.integrations.oauth import CALENDAR_SCOPES, GMAIL_SCOPES

    scopes: list[str] = []
    if kind in ("gmail", "all"):
        scopes.extend(GMAIL_SCOPES)
    if kind in ("calendar", "all"):
        scopes.extend(CALENDAR_SCOPES)
    return scopes
