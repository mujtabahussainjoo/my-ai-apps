"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import httpx
import pytest

from ecommerce_support.core import readiness
from ecommerce_support.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings isolated from any local .env file."""
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


@pytest.fixture(autouse=True)
def _restore_readiness_checks() -> Iterator[None]:
    """Ensure tests that register readiness checks do not leak into others."""
    snapshot = readiness.snapshot_readiness_checks()
    yield
    readiness._checks[:] = snapshot
