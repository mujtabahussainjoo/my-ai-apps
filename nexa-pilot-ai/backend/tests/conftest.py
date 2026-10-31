"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexapilot.api.app import create_app
from nexapilot.core.config import Settings
from nexapilot.core.container import Container


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'nexapilot.db'}",
        secret_backend="memory",
        log_level="WARNING",
        log_json=False,
    )


@pytest.fixture
def container(settings: Settings) -> Iterator[Container]:
    built = Container.create(settings)
    from nexapilot.db.base import initialize_database

    initialize_database(settings)
    try:
        yield built
    finally:
        built.dispose()


@pytest.fixture
def client(settings: Settings, container: Container) -> Iterator[TestClient]:
    app = create_app(settings=settings, container=container, initialize_db=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def memory_secrets(container: Container) -> Any:
    return container.secrets


class FakeProvider:
    """Provider double used to exercise activation without network access."""

    provider_id = "openai"
    model = "gpt-test"
    requires_api_key = True

    def __init__(self, *, ok: bool = True) -> None:
        self._ok = ok
        self.calls = 0

    async def test_connection(self) -> Any:
        from nexapilot.providers.base import ConnectionTestResult

        self.calls += 1
        return ConnectionTestResult(
            ok=self._ok,
            provider=self.provider_id,
            model=self.model,
            message="ok" if self._ok else "unreachable",
        )


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    """Replace provider construction during activation with an offline double."""
    from nexapilot.services import provider_settings

    fake = FakeProvider()

    def _build(session: Any, secrets: Any, config: Any) -> FakeProvider:
        return fake

    monkeypatch.setattr(provider_settings, "build_active_provider", _build)
    return fake
