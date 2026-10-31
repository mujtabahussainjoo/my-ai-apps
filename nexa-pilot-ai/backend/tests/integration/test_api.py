"""API integration tests: settings, single-active-provider invariant, approvals."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from nexapilot.api.app import create_app
from nexapilot.core.config import Settings
from nexapilot.core.container import Container
from nexapilot.db.models import ProviderConfig


def _save_provider(
    client: TestClient,
    *,
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    api_key: str = "sk-test",
    auth_mode: str = "api_key",
    activate: bool = True,
) -> dict[str, Any]:
    payload = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "auth_mode": auth_mode,
        "activate": activate,
    }
    path = "/api/providers/activate" if activate else "/api/providers/configs"
    response = client.post(path, json=payload)
    assert response.status_code < 400, response.text
    return response.json()


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["active_provider"] is None


def test_provider_specs_are_listed(client: TestClient) -> None:
    response = client.get("/api/providers")
    assert response.status_code == 200
    providers = {item["id"] for item in response.json()}
    assert {"openai", "anthropic", "ollama", "gemini", "custom"} <= providers


def test_api_key_is_stored_in_secret_store_not_database(
    client: TestClient, container: Container, fake_provider: Any
) -> None:
    created = _save_provider(client, api_key="sk-super-secret")
    assert created["secret_reference"]
    assert "sk-super-secret" not in str(created)

    session = container.session_factory()
    try:
        config = session.get(ProviderConfig, created["id"])
        assert config is not None
        assert "sk-super-secret" not in str(config.__dict__)
    finally:
        session.close()
    assert container.secrets.get(created["secret_reference"]) == "sk-super-secret"


def test_only_one_provider_is_active(
    client: TestClient, container: Container, fake_provider: Any
) -> None:
    first = _save_provider(client, provider="openai")
    second = _save_provider(client, provider="anthropic", api_key="sk-ant-test")

    session = container.session_factory()
    try:
        active = list(
            session.scalars(select(ProviderConfig).where(ProviderConfig.is_active.is_(True)))
        )
    finally:
        session.close()
    assert len(active) == 1
    assert active[0].id == second["id"]
    assert first["id"] != second["id"]


def test_activation_switch(client: TestClient, container: Container, fake_provider: Any) -> None:
    first = _save_provider(client, provider="openai")
    _save_provider(client, provider="ollama", api_key="", auth_mode="none")

    response = client.post(f"/api/providers/configs/{first['id']}/activate")
    assert response.status_code == 200

    active = client.get("/api/providers/active").json()
    assert active["provider"] == "openai"


def test_deleting_active_provider_leaves_none_active(
    client: TestClient, container: Container, fake_provider: Any
) -> None:
    created = _save_provider(client, provider="openai")
    response = client.delete(f"/api/providers/configs/{created['id']}")
    assert response.status_code == 200

    session = container.session_factory()
    try:
        active = list(
            session.scalars(select(ProviderConfig).where(ProviderConfig.is_active.is_(True)))
        )
    finally:
        session.close()
    assert active == []


def test_chat_without_provider_returns_actionable_error(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/chat",
        json={"message": "hello", "conversation_id": "", "workflow": "", "timezone": "UTC"},
    ) as response:
        body = "".join(response.iter_text())
    assert "no_provider" in body or "provider" in body.lower()
    assert '"type": "error"' in body


def test_settings_patch_validates_values(client: TestClient) -> None:
    bad = client.patch("/api/settings", json={"not_a_setting": True})
    assert bad.status_code == 400

    ok = client.patch("/api/settings", json={"web_search_provider": "brave"})
    assert ok.status_code == 200
    assert ok.json()["settings"]["integrations"]["web_search"]["provider"] == "brave"


def test_settings_reports_active_provider_state(client: TestClient, fake_provider: Any) -> None:
    payload = client.get("/api/settings").json()
    assert payload["active_provider_configured"] is False

    _save_provider(client)
    payload = client.get("/api/settings").json()
    assert payload["active_provider_configured"] is True
    assert payload["active_provider"] == "openai"


def test_approval_list_and_decision(client: TestClient, container: Container) -> None:
    from nexapilot.services import approvals

    session = container.session_factory()
    try:
        request = approvals.create_request(
            session,
            action="email.send",
            title="Send email",
            target="someone@example.com",
            risk="high",
        )
        session.commit()
        approval_id = request.id
    finally:
        session.close()

    listing = client.get("/api/approvals").json()
    assert any(item["id"] == approval_id for item in listing)

    decided = client.post(
        f"/api/approvals/{approval_id}/decide", json={"approved": True, "note": "ok"}
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"

    again = client.post(
        f"/api/approvals/{approval_id}/decide", json={"approved": True, "note": "again"}
    )
    assert again.status_code == 409


def test_activity_endpoint_returns_runs(client: TestClient) -> None:
    response = client.get("/api/activity")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_accounts_endpoint_is_empty_on_fresh_install(client: TestClient) -> None:
    response = client.get("/api/accounts")
    assert response.status_code == 200
    assert response.json() == []


def test_workspace_endpoints_report_missing_configuration(client: TestClient) -> None:
    files = client.get("/api/coding/files")
    assert files.status_code == 409
    assert files.json()["code"] == "not_configured"
    assert files.json()["setup_hint"]


def test_tauri_origins_are_allowed_for_cors(client: TestClient) -> None:
    for origin in ("http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"):
        response = client.options(
            "/api/settings",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200, origin
        assert response.headers["access-control-allow-origin"] == origin


def test_cors_preflight_is_not_blocked_by_api_token(
    settings: Settings, container: Container
) -> None:
    settings.api_token = "secret"
    app = create_app(settings=settings, container=container, initialize_db=False)
    with TestClient(app) as token_client:
        response = token_client.options(
            "/api/settings",
            headers={
                "Origin": "http://tauri.localhost",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_calendar_writes_are_gated_after_argument_validation(client: TestClient) -> None:
    gated = client.post("/api/tools/delete_event", json={"arguments": {"event_id": "evt-1"}})
    assert gated.status_code == 200
    payload = gated.json()
    assert payload["status"] == "approval_required"
    assert payload["approval"]["action"] == "calendar.delete_event"
    assert payload["approval"]["payload"]["tool"] == "delete_event"

    invalid = client.post(
        "/api/tools/update_event",
        json={"arguments": {"event_id": "evt-1", "body": {}}},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "validation_error"


def test_calendar_read_routes_report_missing_account(client: TestClient) -> None:
    paths = [
        "/api/calendar/calendar-list",
        "/api/calendar/calendar-list/primary",
        "/api/calendar/calendars/primary",
        "/api/calendar/colors",
        "/api/calendar/settings",
        "/api/calendar/settings/timezone",
        "/api/calendar/acl",
        "/api/calendar/events/evt-1",
        "/api/calendar/events/evt-1/instances",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 409, path
        assert response.json()["code"] == "not_configured", path

    freebusy = client.post(
        "/api/calendar/freebusy",
        json={
            "time_min": "2026-10-29T00:00:00Z",
            "time_max": "2026-10-30T00:00:00Z",
        },
    )
    assert freebusy.status_code == 409
    assert freebusy.json()["code"] == "not_configured"
