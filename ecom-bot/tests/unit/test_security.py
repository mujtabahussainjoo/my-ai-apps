"""Unit tests for JWT identity primitives (TASK-038, SEC-001)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pydantic
import pytest

from ecommerce_support.core.config import AuthConfig
from ecommerce_support.core.exceptions import AuthenticationError
from ecommerce_support.core.security import (
    GUEST,
    ISSUER,
    Principal,
    create_access_token,
    decode_access_token,
    principal_from_claims,
)

_CONFIG = AuthConfig(jwt_secret="0123456789abcdef0123456789abcdef", jwt_algorithm="HS256")


def test_roundtrip_preserves_subject_and_scopes() -> None:
    token = create_access_token("cust-1", config=_CONFIG, scopes=["support:admin"])
    principal = decode_access_token(token, config=_CONFIG)
    assert principal.user_id == "cust-1"
    assert principal.scopes == frozenset({"support:admin"})
    assert principal.is_authenticated is True
    assert principal.has_scope("support:admin") is True
    assert principal.has_scope("support:agent") is False


def test_guest_principal_is_anonymous() -> None:
    assert GUEST.user_id is None
    assert GUEST.is_authenticated is False
    assert GUEST.has_scope("support:admin") is False


def test_expired_token_rejected_with_reason() -> None:
    issued = datetime.now(UTC) - timedelta(minutes=10)
    token = create_access_token("cust-1", config=_CONFIG, expires_minutes=1, issued_at=issued)
    with pytest.raises(AuthenticationError) as excinfo:
        decode_access_token(token, config=_CONFIG)
    assert excinfo.value.code == "token_expired"


def test_token_signed_with_other_secret_rejected() -> None:
    token = create_access_token("cust-1", config=AuthConfig(jwt_secret="x" * 40))
    with pytest.raises(AuthenticationError):
        decode_access_token(token, config=_CONFIG)


def test_token_from_other_issuer_rejected() -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "cust-1",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "iss": "some-other-service",
        },
        _CONFIG.jwt_secret,
        algorithm=_CONFIG.jwt_algorithm,
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(token, config=_CONFIG)


def test_malformed_token_rejected() -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token("not-a-jwt", config=_CONFIG)


def test_claims_without_subject_rejected() -> None:
    with pytest.raises(AuthenticationError):
        principal_from_claims({"scope": "support:admin"})


def test_claims_scope_accepts_blank() -> None:
    principal = principal_from_claims({"sub": "cust-1", "scope": ""})
    assert principal.scopes == frozenset()


def test_principal_rejects_unknown_fields() -> None:
    with pytest.raises(pydantic.ValidationError):
        Principal(user_id="cust-1", is_admin=True)  # type: ignore[call-arg]


def test_issuer_constant_is_stable() -> None:
    assert ISSUER == "ecommerce-support"
