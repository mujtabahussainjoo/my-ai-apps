"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from ecommerce_support.core.config import Settings, get_settings
from ecommerce_support.core.observability import current_request_id


def get_settings_dep() -> Settings:
    """Provide the settings singleton to route handlers."""
    return get_settings()


def get_request_id(request: Request) -> str:
    """Return the correlation id for the current request."""
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = current_request_id() or ""
    return rid
