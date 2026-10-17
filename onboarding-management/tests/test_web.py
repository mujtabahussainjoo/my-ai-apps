"""Dashboard: pages, JSON APIs, scenario runner, human-in-the-loop."""

import pytest
from fastapi.testclient import TestClient

from app.ai_helper import AIHelper
from app.chat_agent import ChatAgent
from web.main import create_app
from web.state import WebState


@pytest.fixture
def web_state(tmp_path):
    return WebState(
        live=False,
        ledger_path=tmp_path / "ledger.json",
        exceptions_path=tmp_path / "exceptions.json",
        audit_path=tmp_path / "audit.jsonl",
        tracker_path=tmp_path / "tasks.json",
        ai=AIHelper(api_key=""),
        chat_agent=ChatAgent(api_key=""),
    )


@pytest.fixture
def client(web_state):
    app = create_app(web_state)
    with TestClient(app) as test_client:
        yield test_client


def test_dashboard_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Onboarding Integration" in response.text
    assert "Run a demo scenario" in response.text
    assert "AI copilot" in response.text


def test_dashboard_has_real_system_tabs(client):
    response = client.get("/")

    for name in [
        "Ashby",
        "Workday",
        "Okta / Lumos",
        "Google Workspace",
        "Slack",
        "Equipment / ExpoIT",
        "Onboarding cohort tracker",
    ]:
        assert name in response.text


def test_scenarios_listed_on_dashboard(client):
    response = client.get("/")

    assert 'data-scenario="new_hire"' in response.text
    assert 'data-scenario="location_conflict"' in response.text


def test_summary_starts_empty(client):
    summary = client.get("/api/summary").json()

    assert summary["open_exceptions"] == 0
    assert summary["failed_operations"] == 0


def test_run_scenario_completes(client):
    result = client.post("/api/scenarios/new_hire").json()

    assert result["overall_status"] == "COMPLETED"
    assert result["employee_id"] == "EMP-100"
    assert any(o["target"] == "workday" for o in result["outcomes"])


def test_location_conflict_needs_review_and_creates_exception(client):
    result = client.post("/api/scenarios/location_conflict").json()

    assert result["overall_status"] == "NEEDS_REVIEW"
    exceptions = client.get("/api/exceptions").json()["exceptions"]
    assert any(e["status"] == "OPEN" for e in exceptions)

    summary = client.get("/api/summary").json()
    assert summary["open_exceptions"] >= 1


def test_resolve_exception_logs_audit(client):
    client.post("/api/scenarios/location_conflict")
    exception_id = client.get("/api/exceptions").json()["exceptions"][0]["exception_id"]

    resolved = client.post(
        f"/api/exceptions/{exception_id}/resolve",
        json={"by": "alice", "resolution": "confirmed Hyderabad"},
    ).json()

    assert resolved["status"] == "RESOLVED"
    assert resolved["resolved_by"] == "alice"

    audit = client.get("/api/audit").json()["entries"]
    assert any(
        e.get("entry_type") == "exception" and e.get("exception_id") == exception_id
        for e in audit
    )


def test_resolve_unknown_exception_404(client):
    response = client.post(
        "/api/exceptions/exc-missing/resolve", json={"by": "x", "resolution": "y"}
    )

    assert response.status_code == 404


def test_unknown_scenario_404(client):
    assert client.post("/api/scenarios/does_not_exist").status_code == 404


def test_transient_failure_recovers(client):
    result = client.post("/api/scenarios/equipment_transient").json()

    equipment = next(o for o in result["outcomes"] if o["target"] == "equipment")
    assert equipment["status"] == "SUCCESS"
    assert equipment["attempts"] >= 2


def test_persistent_failure_is_partial(client):
    result = client.post("/api/scenarios/equipment_persistent").json()

    assert result["overall_status"] == "PARTIALLY_COMPLETED"


def test_tasks_and_monitor_view(client):
    data = client.get("/api/tasks").json()

    assert data["tasks"]
    assert data["monitor"]["overdue"] >= 1

    run = client.post("/api/monitor/run").json()
    assert run["reminders_sent"] >= 1


def test_ledger_populated_after_run(client):
    client.post("/api/scenarios/new_hire")
    ledger = client.get("/api/ledger").json()["ledger"]

    assert ledger
    assert any(row["status"] == "SUCCESS" for row in ledger)


def test_chat_uses_fallback_when_ai_disabled(client):
    client.post("/api/scenarios/location_conflict")

    response = client.post("/api/chat", json={"message": "any exceptions?"}).json()

    assert response["ai_used"] is False
    assert response["intent"] == "exceptions"
    assert "exc-" in response["reply"]


def test_reset_clears_state(client):
    client.post("/api/scenarios/new_hire")
    assert client.get("/api/summary").json()["skipped_operations"] >= 0

    assert client.post("/api/reset").json() == {"status": "reset"}

    summary = client.get("/api/summary").json()
    assert summary["open_exceptions"] == 0
    assert summary["successful_operations"] == 0
    assert summary["skipped_operations"] == 0
    assert client.get("/api/ledger").json()["ledger"] == []
    assert client.get("/api/audit").json()["entries"] == []


def test_systems_catalog_uses_real_names(client):
    systems = client.get("/api/systems").json()["systems"]
    by_key = {s["key"]: s for s in systems}

    assert by_key["workday"]["display_name"] == "Workday"
    assert by_key["google_workspace"]["display_name"] == "Google Workspace"
    assert by_key["cohort_tracker"]["display_name"] == "Onboarding cohort tracker"
    assert by_key["ashby"]["kind"] == "source"
    assert by_key["ai"]["kind"] == "ai"


def test_target_system_records_after_run(client):
    client.post("/api/scenarios/new_hire")

    workday = client.get("/api/systems/workday").json()
    assert workday["record_count"] >= 1
    assert any(r["employee_id"] == "EMP-100" for r in workday["records"])


def test_source_inbox_records_events(client):
    client.post("/api/scenarios/new_hire")

    ashby = client.get("/api/systems/ashby").json()
    assert ashby["record_count"] >= 1
    assert any(r["event_id"] == "event-101" for r in ashby["records"])


def test_ai_portal_lists_classifications(client):
    client.post("/api/scenarios/location_conflict")

    ai = client.get("/api/systems/ai").json()
    assert ai["enabled"] is False
    assert "human_review" in ai["allowed_actions"]
    assert ai["record_count"] >= 1


def test_unknown_system_404(client):
    assert client.get("/api/systems/does-not-exist").status_code == 404


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}
