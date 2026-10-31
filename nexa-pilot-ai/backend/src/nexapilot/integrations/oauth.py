"""OAuth 2.0 helpers for Google APIs.

Only the authorisation-code flow is used, with PKCE. Refresh tokens are stored in
the OS secret vault, keyed per account, so accounts stay isolated.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from nexapilot.core.errors import IntegrationError
from nexapilot.providers.http import classify_status, wrap_transport_error

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
)
CALENDAR_SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
GMAIL_READONLY_SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str = ""
    expires_at: datetime | None = None
    scopes: list[str] | None = None
    token_type: str = "Bearer"

    def is_expired(self, *, leeway_seconds: int = 60) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= (self.expires_at - timedelta(seconds=leeway_seconds))

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": self.scopes or [],
            "token_type": self.token_type,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> OAuthTokens:
        expires_at = None
        raw_expires = payload.get("expires_at")
        if isinstance(raw_expires, str):
            try:
                expires_at = datetime.fromisoformat(raw_expires)
            except ValueError:
                expires_at = None
        return cls(
            access_token=str(payload.get("access_token") or ""),
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_at=expires_at,
            scopes=list(payload.get("scopes") or []),
            token_type=str(payload.get("token_type") or "Bearer"),
        )


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...] | list[str],
    state: str,
    code_verifier: str,
    access_type: str = "offline",
    prompt: str = "consent",
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge(code_verifier),
        "code_challenge_method": "S256",
        "access_type": access_type,
        "prompt": prompt,
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    timeout: float = 30.0,
    transport: Any = None,
) -> OAuthTokens:
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(
        timeout=timeout, transport=transport, follow_redirects=False
    ) as client:
        try:
            response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, "Google OAuth", timeout) from exc
        if response.status_code >= 400:
            raise classify_status(response.status_code, "Google OAuth", response.text)
        data = response.json()
    return _tokens_from_payload(data)


async def refresh_tokens(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: float = 30.0,
    transport: Any = None,
) -> OAuthTokens:
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(
        timeout=timeout, transport=transport, follow_redirects=False
    ) as client:
        try:
            response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, "Google OAuth", timeout) from exc
        if response.status_code >= 400:
            raise classify_status(response.status_code, "Google OAuth", response.text)
        data = response.json()
    tokens = _tokens_from_payload(data)
    if not tokens.refresh_token:
        tokens.refresh_token = refresh_token
    return tokens


def _tokens_from_payload(data: dict[str, Any]) -> OAuthTokens:
    if not data.get("access_token"):
        raise IntegrationError("Google OAuth did not return an access token")
    expires_in = int(data.get("expires_in") or 3600)
    scope_raw = data.get("scope") or ""
    scopes = [item for item in scope_raw.split() if item]
    return OAuthTokens(
        access_token=str(data["access_token"]),
        refresh_token=str(data.get("refresh_token") or ""),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        scopes=scopes,
        token_type=str(data.get("token_type") or "Bearer"),
    )


def account_secret_reference(account_id: str, kind: str = "tokens") -> str:
    """Secret reference for one account. Accounts never share a token slot."""
    return f"account:{account_id}:{kind}"
