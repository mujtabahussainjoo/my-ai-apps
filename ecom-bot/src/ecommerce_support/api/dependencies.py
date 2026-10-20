"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.api.wiring import AppWiring
from ecommerce_support.core.config import Settings, get_settings
from ecommerce_support.core.exceptions import (
    AuthenticationError,
    RateLimitError,
)
from ecommerce_support.core.observability import current_request_id
from ecommerce_support.core.ratelimit import SlidingWindowRateLimiter, get_rate_limiter
from ecommerce_support.core.security import GUEST, Principal, decode_access_token
from ecommerce_support.db.session import get_session_factory
from ecommerce_support.guardrails.authorization import (
    require_authenticated,
)
from ecommerce_support.guardrails.authorization import (
    require_scope as require_scope_policy,
)
from ecommerce_support.services import ChatService, FeedbackService, TicketService
from ecommerce_support.services.conversations import ConversationService
from ecommerce_support.services.documents import DocumentService

_wiring: AppWiring | None = None


def get_wiring() -> AppWiring:
    """Return the process-wide composition root (cached, stateless collaborators)."""
    global _wiring
    if _wiring is None:
        _wiring = AppWiring(get_settings())
    return _wiring


def reset_wiring() -> None:
    """Drop the cached composition root (used by tests after config changes)."""
    global _wiring
    _wiring = None


def get_settings_dep() -> Settings:
    """Provide the settings singleton to route handlers."""
    return get_settings()


def get_principal(request: Request, settings: Settings = Depends(get_settings_dep)) -> Principal:
    """Resolve the caller identity from a JWT ``Authorization: Bearer`` header (SEC-001).

    Absent credentials yield the anonymous :data:`GUEST` principal (public/guest access is
    allowed); a present-but-invalid token raises ``401`` rather than silently degrading to guest.
    """
    header = request.headers.get("Authorization")
    if not header:
        return GUEST
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Authorization header must use the Bearer scheme.")
    return decode_access_token(token.strip(), config=settings.auth)


def get_user_id(principal: Principal = Depends(get_principal)) -> str | None:
    """Return the authenticated user id, or ``None`` for a guest."""
    return principal.user_id


def get_required_user_id(principal: Principal = Depends(get_principal)) -> str:
    """Require an authenticated caller and return their user id (else ``401``)."""
    return require_authenticated(principal.user_id)


def require_scope(scope: str) -> Callable[[Principal], Principal]:
    """Build a dependency that requires ``scope`` on the caller's token (SEC-001)."""

    def _dependency(principal: Principal = Depends(get_principal)) -> Principal:
        require_scope_policy(principal.scopes, scope, user_id=principal.user_id)
        return principal

    return _dependency


def get_tenant_id() -> str:
    """Resolve the tenant scope for the current request (single-tenant until TASK-038)."""
    return "default"


def get_request_id(request: Request) -> str:
    """Return the correlation id for the current request."""
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = current_request_id() or ""
    return rid


def enforce_chat_rate_limit(
    request: Request,
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings_dep),
    limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
) -> None:
    """Reject chat requests over the per-client budget with ``429`` (NFR-004, SEC-012).

    The client key is the authenticated user id when present, otherwise the peer address.
    """
    key = principal.user_id or _client_key(request)
    decision = limiter.check(key, limit=settings.limits.rate_limit_per_minute)
    if not decision.allowed:
        raise RateLimitError(
            "Too many requests. Please wait a moment and try again.",
            details={"retry_after_seconds": decision.retry_after_seconds},
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "anonymous"


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide a request-scoped DB session, committing on success and rolling back on error.

    Repositories only ``flush``; this dependency owns the transaction boundary at the transport.
    Tests override it (or the higher-level service dependency) to avoid a live database.
    """
    session = get_session_factory()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_feedback_service(session: AsyncSession = Depends(get_session)) -> FeedbackService:
    """Build the feedback service bound to the request session."""
    return FeedbackService.from_session(session)


def get_chat_service(
    session: AsyncSession = Depends(get_session),
    wiring: AppWiring = Depends(get_wiring),
) -> ChatService:
    """Build the chat service (agent graph + ticketing) bound to the request session."""
    return wiring.build_chat_service(session)


def get_conversation_service(
    session: AsyncSession = Depends(get_session),
    wiring: AppWiring = Depends(get_wiring),
) -> ConversationService:
    """Build the conversation service bound to the request session."""
    return wiring.build_conversation_service(session)


def get_ticket_service(
    session: AsyncSession = Depends(get_session),
    wiring: AppWiring = Depends(get_wiring),
) -> TicketService:
    """Build the ticket service bound to the request session."""
    return wiring.build_ticket_service(session)


def get_document_service(
    session: AsyncSession = Depends(get_session),
    wiring: AppWiring = Depends(get_wiring),
) -> DocumentService:
    """Build the document service bound to the request session."""
    return wiring.build_document_service(session)
