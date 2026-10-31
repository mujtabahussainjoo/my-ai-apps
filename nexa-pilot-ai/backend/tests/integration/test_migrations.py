"""Migration tests: the schema can be created, rolled back and re-created."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migrations_round_trip(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    config = _alembic_config(database_url)

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
        for expected in (
            "alembic_version",
            "provider_config",
            "secret_reference",
            "conversation",
            "message",
            "task_run",
            "approval_request",
            "connected_account",
            "email_message",
            "calendar_event",
            "portfolio",
            "position",
            "order",
            "watchlist_item",
            "audit_log",
        ):
            assert expected in tables, f"missing table: {expected}"

        command.downgrade(config, "base")
        with engine.connect() as connection:
            remaining = set(inspect(connection).get_table_names())
        assert remaining <= {"alembic_version"}

        command.upgrade(config, "head")
        with engine.connect() as connection:
            recreated = set(inspect(connection).get_table_names())
        assert "conversation" in recreated
    finally:
        engine.dispose()


def test_active_provider_is_unique_by_query(tmp_path: Path) -> None:
    """The single-active-provider rule holds at the SQL level too."""
    from sqlalchemy.orm import Session

    from nexapilot.core.secrets import MemorySecretStore
    from nexapilot.db.models import ProviderConfig
    from nexapilot.services.provider_settings import activate_existing

    database_url = f"sqlite:///{tmp_path / 'unique.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            first = ProviderConfig(
                provider="openai",
                model="gpt-4o-mini",
                base_url="https://api.openai.com/v1",
                auth_mode="api_key",
                secret_reference="ref-a",
                is_active=True,
                capabilities={},
            )
            second = ProviderConfig(
                provider="anthropic",
                model="claude-sonnet-4-5",
                base_url="https://api.anthropic.com",
                auth_mode="api_key",
                secret_reference="ref-b",
                is_active=False,
                capabilities={},
            )
            session.add_all([first, second])
            session.commit()

            import asyncio

            asyncio.run(activate_existing(session, MemorySecretStore(), second, validate=False))
            session.commit()

            active = session.scalars(
                select(ProviderConfig).where(ProviderConfig.is_active.is_(True))
            ).all()
            assert [item.provider for item in active] == ["anthropic"]
    finally:
        engine.dispose()


def test_settings_defaults_are_importable() -> None:
    from nexapilot.core.config import Settings

    settings = Settings(environment="test", secret_backend="memory")
    assert settings.max_tool_iterations > 0
    assert settings.max_agent_steps > 0
    assert settings.finance_max_order_value > 0
    assert settings.finance_max_order_quantity > 0


def test_provider_env_overrides(tmp_path: Path) -> None:
    from nexapilot.core.config import Settings

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'env.db'}",
        secret_backend="memory",
        web_search_provider="tavily",
    )
    assert settings.web_search_provider == "tavily"
    assert settings.effective_database_url.endswith("env.db")


@pytest.mark.parametrize("backend", ["memory", "file"])
def test_secret_backend_selection(tmp_path: Path, backend: str) -> None:
    from nexapilot.core.secrets import build_secret_store

    store = build_secret_store(backend, data_dir=tmp_path)
    store.set("ref", "value")
    assert store.get("ref") == "value"
