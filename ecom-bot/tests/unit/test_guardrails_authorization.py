"""Unit tests for authorization policies (TASK-039, SEC-002/SEC-008/FR-040)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
)
from ecommerce_support.guardrails.authorization import (
    AuthorizationPolicy,
    require_authenticated,
    require_ownership,
    require_scope,
)


def test_require_authenticated_returns_user_id() -> None:
    assert require_authenticated("u-1") == "u-1"


def test_require_authenticated_rejects_anonymous() -> None:
    with pytest.raises(AuthenticationError) as excinfo:
        require_authenticated(None)
    assert excinfo.value.http_status == 401


def test_require_scope_rejects_anonymous_with_401() -> None:
    with pytest.raises(AuthenticationError) as excinfo:
        require_scope(frozenset({"support:admin"}), "support:admin")
    assert excinfo.value.http_status == 401


def test_require_scope_rejects_underprivileged_with_403() -> None:
    with pytest.raises(AuthorizationError) as excinfo:
        require_scope(frozenset({"read"}), "support:admin", user_id="u-1")
    assert excinfo.value.http_status == 403


def test_require_scope_allows_matching_scope() -> None:
    require_scope(frozenset({"support:admin"}), "support:admin", user_id="u-1")


def test_require_ownership_allows_owner() -> None:
    require_ownership("u-1", "u-1")


def test_require_ownership_hides_other_users_resource() -> None:
    with pytest.raises(NotFoundError) as excinfo:
        require_ownership("u-1", "u-2")
    assert excinfo.value.http_status == 404


def test_policy_namespace_exposes_functions() -> None:
    assert callable(AuthorizationPolicy.require_authenticated)
    assert callable(AuthorizationPolicy.require_scope)
    assert callable(AuthorizationPolicy.require_ownership)
