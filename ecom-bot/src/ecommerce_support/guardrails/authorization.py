"""Authorization policies as code (SEC-002, SEC-008, FR-040).

Security is not a prompt: every policy here is a plain function that raises a typed
:class:`~ecommerce_support.core.exceptions.AppError` on denial. Transport dependencies, services,
and tools all call into this module so the rule lives in exactly one place.
"""

from __future__ import annotations

from collections.abc import Iterable

from ecommerce_support.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError


def require_authenticated(user_id: str | None) -> str:
    """Return ``user_id`` or raise ``401`` when the caller is anonymous (SEC-002)."""
    if not user_id:
        raise AuthenticationError("Authentication is required for this request.")
    return user_id


def require_scope(scopes: Iterable[str], scope: str, *, user_id: str | None = None) -> None:
    """Require ``scope`` for the caller; ``401`` when anonymous, ``403`` when under-privileged."""
    if not user_id:
        raise AuthenticationError("Authentication is required for this request.")
    if scope not in set(scopes):
        raise AuthorizationError(
            "You do not have access to this resource.", details={"required_scope": scope}
        )


def require_ownership(owner_id: str | None, caller_id: str | None) -> None:
    """Allow access only when ``caller_id`` owns the resource (SEC-002).

    A mismatch is reported as ``404`` so the existence of another party's resource is not leaked.
    """
    if owner_id is None or owner_id != caller_id:
        raise NotFoundError("Resource not found.")


class AuthorizationPolicy:
    """Namespaced accessors for the module-level policy functions."""

    require_authenticated = staticmethod(require_authenticated)
    require_scope = staticmethod(require_scope)
    require_ownership = staticmethod(require_ownership)


__all__ = [
    "AuthorizationPolicy",
    "require_authenticated",
    "require_ownership",
    "require_scope",
]
