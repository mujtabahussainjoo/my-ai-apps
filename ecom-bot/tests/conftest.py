"""Shared test fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest

from ecommerce_support.core import readiness
from ecommerce_support.core.config import Settings, get_settings
from ecommerce_support.core.ratelimit import reset_rate_limiter

# Keep JWTs minted by tests interchangeable with the app's own settings (SEC-001), and
# avoid PyJWT's weak-HMAC-key warning for the placeholder development secret.
os.environ.setdefault("AUTH__JWT_SECRET", "unit-test-secret-0123456789abcdef-0123456789")


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    """Return test settings with dotenv disabled (env overrides remain active)."""
    return Settings(_env_file=None)


@pytest.fixture
def app(settings: Settings):
    from ecommerce_support.main import create_app

    return create_app(settings)


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def make_token(settings: Settings) -> Callable[..., str]:
    """Return a factory that mints a signed JWT for a subject/scope set (SEC-001)."""
    from ecommerce_support.core.security import create_access_token

    def _make(subject: str = "u-1", scopes: list[str] | None = None) -> str:
        return create_access_token(subject, config=settings.auth, scopes=scopes or [])

    return _make


@pytest.fixture
def auth_headers(make_token: Callable[..., str]) -> Callable[..., dict[str, str]]:
    """Return a factory for an ``Authorization: Bearer`` header."""

    def _headers(subject: str = "u-1", scopes: list[str] | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(subject, scopes)}"}

    return _headers


class AllowAllConversationAccess:
    """Test double for the ownership gate: every conversation looks owned."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def assert_access(self, conversation_id: str, *, user_id: str | None) -> Any:
        self.calls.append((conversation_id, user_id))
        return None


@pytest.fixture
def conversation_access() -> AllowAllConversationAccess:
    return AllowAllConversationAccess()


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> Iterator[None]:
    """Isolate the process-wide rate limiter between tests."""
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture(autouse=True)
def _restore_readiness_checks() -> Iterator[None]:
    """Ensure tests that register readiness checks do not leak into others."""
    snapshot = readiness.snapshot_readiness_checks()
    yield
    readiness._checks[:] = snapshot
