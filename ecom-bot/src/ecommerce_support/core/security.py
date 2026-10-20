"""JWT identity primitives (SEC-001).

Framework-free: PyJWT only, no FastAPI/Starlette imports, so identity logic is unit-testable
without a running app. The transport layer resolves a request's principal and passes its
``user_id`` down to the services, which enforce ownership.

A ``Principal`` models either an authenticated customer (``user_id`` set from the token subject)
or a guest (``user_id`` is ``None``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from ecommerce_support.core.config import AuthConfig
from ecommerce_support.core.exceptions import AuthenticationError
from ecommerce_support.schemas.common import Schema

ISSUER = "ecommerce-support"


class Principal(Schema):
    """The authenticated caller for a request (guest when ``user_id`` is ``None``)."""

    user_id: str | None = None
    scopes: frozenset[str] = frozenset()

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


GUEST = Principal()


def create_access_token(
    subject: str,
    *,
    config: AuthConfig,
    scopes: list[str] | None = None,
    expires_minutes: int | None = None,
    issued_at: datetime | None = None,
) -> str:
    """Mint a signed access token for ``subject`` (used by tests and a future login endpoint)."""
    now = issued_at or datetime.now(UTC)
    minutes = expires_minutes if expires_minutes is not None else config.jwt_expires_minutes
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        "iss": ISSUER,
        "scope": " ".join(scopes or []),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    """Build a :class:`Principal` from decoded claims (validates the subject)."""
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthenticationError(
            "Token is missing a subject.", details={"reason": "invalid_subject"}
        )
    scope_field = claims.get("scope", "")
    scopes = frozenset(scope_field.split()) if isinstance(scope_field, str) else frozenset()
    return Principal(user_id=subject.strip(), scopes=scopes)


def decode_access_token(token: str, *, config: AuthConfig) -> Principal:
    """Validate a signed access token and return its principal.

    Raises :class:`AuthenticationError` (401) for any invalid/expired/malformed token; the
    reason is intentionally coarse so responses do not leak verification details (SEC-002).
    """
    try:
        claims = jwt.decode(
            token,
            config.jwt_secret,
            algorithms=[config.jwt_algorithm],
            issuer=ISSUER,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthenticationError(
            "Your session has expired. Please sign in again.", code="token_expired"
        ) from None
    except jwt.InvalidTokenError:
        raise AuthenticationError("Invalid or malformed authentication token.") from None
    return principal_from_claims(claims)


__all__ = ["GUEST", "ISSUER", "Principal", "create_access_token", "principal_from_claims"]
