"""End-to-end demo of the onboarding change-propagation workflow.

Runs entirely in-process (the mock demo portal is driven through
Starlette's ``TestClient``), so no server is required::

    python run_demo.py

To talk to a separately-running demo portal instead::

    python -m demo_portal.main          # terminal 1
    python run_demo.py --live           # terminal 2
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta

from fastapi.testclient import TestClient

from adapters.client import DemoPortalClient
from app.ai_helper import AIHelper
from app.audit_logger import AuditLogger
from app.config import settings
from app.deadline_monitor import ConsoleNotifier, DeadlineMonitor
from app.event_receiver import parse_event
from app.exception_handler import ExceptionHandler
from app.idempotency_store import IdempotencyStore
from app.orchestrator import Orchestrator, WorkflowResult
from app.retry_handler import RetryHandler
from app.task_store import TaskStore
from demo_portal.main import app as demo_app

SAMPLE_DIR = settings.ledger_path.parent.parent / "sample_events"


def _load(name: str) -> dict:
    return json.loads((SAMPLE_DIR / name).read_text())


def _show(label: str, result: WorkflowResult) -> None:
    print(f"\n=== {label} ===")
    print(f"  overall: {result.overall_status.value}  ({result.message})")
    for outcome in result.outcomes:
        print(
            f"    - {outcome.target:16} {outcome.status:18} "
            f"attempts={outcome.attempts} :: {outcome.detail}"
        )
    if result.blocked:
        for target, fields in result.blocked.items():
            print(f"    ! blocked {target}: {fields}")
    for exception_id in result.exceptions:
        exception = None
        # exceptions are fetched by the caller via the orchestrator
        print(f"    ~ exception {exception_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Onboarding workflow demo")
    parser.add_argument(
        "--live",
        action="store_true",
        help="use the demo portal at DEMO_PORTAL_URL instead of in-process",
    )
    args = parser.parse_args()

    if args.live:
        portal = DemoPortalClient()
        test_client = None
        print(f"Using live demo portal at {settings.demo_portal_url}")
    else:
        test_client = TestClient(demo_app)
        test_client.post("/_admin/reset")
        portal = DemoPortalClient(base_url="http://testserver", client=test_client)
        print("Using in-process demo portal (no server required)")

    orchestrator = Orchestrator(
        portal=portal,
        ledger=IdempotencyStore(),
        exception_handler=ExceptionHandler(),
        retry_handler=RetryHandler(),
        audit=AuditLogger(),
        ai=AIHelper(),
    )
    orchestrator.ledger.clear()
    orchestrator.exceptions.clear()
    orchestrator.audit.clear()

    def fault(target: str, mode: str, remaining: int) -> None:
        request = {"target": target, "mode": mode, "remaining": remaining}
        if test_client is not None:
            test_client.post("/_admin/faults", json=request)

    print("\n######## CHANGE PROPAGATION ########")
    _show("A. Valid new hire", orchestrator.process(parse_event(_load("new_hire.json"))))
    _show(
        "A. Start-date change",
        orchestrator.process(parse_event(_load("start_date_changed.json"))),
    )
    _show(
        "Duplicate event (idempotency)",
        orchestrator.process(parse_event(_load("start_date_changed.json"))),
    )
    _show(
        "B. Location conflict (validation gate)",
        orchestrator.process(parse_event(_load("location_conflict.json"))),
    )
    _show(
        "D. Off-cycle hire",
        orchestrator.process(parse_event(_load("off_cycle_hire.json"))),
    )

    print("\n######## FAILURE HANDLING ########")
    if test_client is not None:
        test_client.post("/_admin/reset")
        orchestrator.ledger.clear()
    fault("equipment", "temporary", 1)
    _show(
        "C. Transient equipment failure -> retry recovers",
        orchestrator.process(parse_event(_load("new_hire.json"))),
    )

    if test_client is not None:
        test_client.post("/_admin/reset")
        orchestrator.ledger.clear()
    fault("equipment", "temporary", -1)
    _show(
        "C. Persistent equipment failure -> partial",
        orchestrator.process(parse_event(_load("new_hire.json"))),
    )

    if test_client is not None:
        test_client.post("/_admin/reset")
        orchestrator.ledger.clear()
    fault("equipment", "timeout", 1)
    _show(
        "C. Equipment timeout (unknown) -> reconcile",
        orchestrator.process(parse_event(_load("new_hire.json"))),
    )

    _show("Malformed event", orchestrator.handle({"event_id": "broken"}))

    print("\n######## OPEN EXCEPTIONS ########")
    for exception in orchestrator.exceptions.open_exceptions():
        print(
            f"  {exception.exception_id} {exception.exception_type:26} "
            f"field={exception.field_name} action={exception.recommended_action} "
            f"ai_used={exception.ai_used}"
        )

    print("\n######## DEADLINE MONITOR ########")
    task_store = TaskStore()
    monitor = DeadlineMonitor(store=task_store, notifier=ConsoleNotifier(), warn_days=7)
    report = monitor.run()
    print(
        f"  run 1: approaching={report.approaching} overdue={report.overdue} "
        f"reminders_sent={report.reminders_sent}"
    )
    report2 = monitor.run()
    print(f"  run 2 (no duplicates): reminders_sent={report2.reminders_sent}")

    print("\nDone.")


if __name__ == "__main__":
    main()
