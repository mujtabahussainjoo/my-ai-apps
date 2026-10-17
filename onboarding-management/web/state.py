"""Shared, in-process state for the dashboard.

The dashboard is a thin, **read-mostly** view over the same collaborators
the demo uses: the orchestrator (workflow), the exception handler, the
audit log, the task store and the deadline monitor. By default the demo
portal runs in-process (Starlette ``TestClient``) so the whole UI works
with a single command and no second server.

The one mutating action exposed to an operator is resolving an exception
(human-in-the-loop); running a demo scenario is explicit and opt-in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adapters.client import DemoPortalClient
from app.ai_helper import ALLOWED_ACTIONS, AIHelper
from app.audit_logger import AuditLogger
from app.chat_agent import ChatAgent
from app.config import BASE_DIR, settings
from app.deadline_monitor import DeadlineMonitor, RecordingNotifier
from app.exception_handler import ExceptionHandler
from app.idempotency_store import IdempotencyStore
from app.models import OverallStatus
from app.orchestrator import Orchestrator, WorkflowResult
from app.systems import SYSTEM_CATALOG, SystemInfo
from app.task_store import TaskStore

SAMPLE_DIR = BASE_DIR / "sample_events"


@dataclass
class Scenario:
    key: str
    label: str
    description: str
    event: dict[str, Any]
    faults: list[dict[str, Any]] = field(default_factory=list)
    reset_first: bool = False


def _load_event(name: str) -> dict[str, Any]:
    return json.loads((SAMPLE_DIR / name).read_text())


def _scenarios() -> dict[str, Scenario]:
    new_hire = _load_event("new_hire.json")
    scenarios = [
        Scenario(
            key="new_hire",
            label="A. Valid new hire",
            description="New hire propagates to every system and is verified.",
            event=new_hire,
        ),
        Scenario(
            key="start_date_change",
            label="A. Start-date change",
            description="Only dependent systems are updated for a date change.",
            event=_load_event("start_date_changed.json"),
        ),
        Scenario(
            key="duplicate_event",
            label="Duplicate event (idempotency)",
            description="Replaying the same event causes no duplicate effects.",
            event=_load_event("start_date_changed.json"),
        ),
        Scenario(
            key="location_conflict",
            label="B. Location conflict",
            description="Cross-system conflict blocks unsafe updates for review.",
            event=_load_event("location_conflict.json"),
        ),
        Scenario(
            key="off_cycle_hire",
            label="D. Off-cycle hire",
            description="A hire outside Ashby uses the exact same workflow.",
            event=_load_event("off_cycle_hire.json"),
        ),
        Scenario(
            key="equipment_transient",
            label="C. Transient equipment failure",
            description="Temporary failure retries with backoff and recovers.",
            event=new_hire,
            faults=[{"target": "equipment", "mode": "temporary", "remaining": 1}],
            reset_first=True,
        ),
        Scenario(
            key="equipment_persistent",
            label="C. Persistent equipment failure",
            description="Retries exhausted -> partial completion + escalation.",
            event=new_hire,
            faults=[{"target": "equipment", "mode": "temporary", "remaining": -1}],
            reset_first=True,
        ),
        Scenario(
            key="equipment_timeout",
            label="C. Equipment timeout (unknown)",
            description="Unknown outcome is reconciled before any retry.",
            event=new_hire,
            faults=[{"target": "equipment", "mode": "timeout", "remaining": 1}],
            reset_first=True,
        ),
        Scenario(
            key="malformed_event",
            label="Malformed event",
            description="Bad envelopes are rejected before any processing.",
            event={"event_id": "broken"},
        ),
    ]
    return {s.key: s for s in scenarios}


class WebState:
    def __init__(
        self,
        *,
        live: bool = False,
        ledger_path: str | Path | None = None,
        exceptions_path: str | Path | None = None,
        audit_path: str | Path | None = None,
        tracker_path: str | Path | None = None,
        tracker_seed: str | Path | None = None,
        ai: AIHelper | None = None,
        chat_agent: ChatAgent | None = None,
    ) -> None:
        self.live = live
        self._test_client = None
        if live:
            self.portal = DemoPortalClient()
        else:
            from fastapi.testclient import TestClient

            from demo_portal.main import app as demo_app

            self._test_client = TestClient(demo_app)
            self._test_client.post("/_admin/reset")
            self.portal = DemoPortalClient(
                base_url="http://testserver", client=self._test_client
            )

        self.orchestrator = Orchestrator(
            portal=self.portal,
            ledger=IdempotencyStore(path=ledger_path),
            exception_handler=ExceptionHandler(path=exceptions_path),
            audit=AuditLogger(path=audit_path),
            ai=ai or AIHelper(),
        )
        self.task_store = TaskStore(path=tracker_path, seed_path=tracker_seed)
        self.monitor = DeadlineMonitor(
            store=self.task_store, notifier=RecordingNotifier()
        )
        self.chat_agent = chat_agent or ChatAgent()
        self.scenarios = _scenarios()

    # -- scenarios ---------------------------------------------------------
    def run_scenario(self, key: str) -> WorkflowResult:
        scenario = self.scenarios.get(key)
        if scenario is None:
            raise KeyError(key)
        if scenario.reset_first:
            self._reset_portal()
            self.orchestrator.ledger.clear()
        for fault in scenario.faults:
            self._inject_fault(fault)
        self._record_source_event(scenario.event)
        return self.orchestrator.handle(scenario.event)

    def _record_source_event(self, event: Any) -> None:
        """Drop the incoming event into the source system's inbox (Ashby)."""
        if not isinstance(event, dict):
            return
        if not event.get("event_id") or not event.get("employee_id"):
            return
        try:
            self.portal.client.post("/ashby/events", json=event)
        except Exception:  # noqa: BLE001 - recording is best-effort for the demo
            pass

    def _reset_portal(self) -> None:
        self.portal.client.post("/_admin/reset")

    def _inject_fault(self, fault: dict[str, Any]) -> None:
        self.portal.client.post("/_admin/faults", json=fault)

    # -- portal helpers ----------------------------------------------------
    def _portal_get(self, path: str) -> Any:
        try:
            response = self.portal.client.get(path)
            if response.status_code >= 400:
                return None
            return response.json()
        except Exception:  # noqa: BLE001 - the dashboard must never 500 on a view
            return None

    def _system_records(self, info: SystemInfo) -> tuple[list[dict[str, Any]], bool]:
        """Return (records, connected) for one system from the demo portal."""
        if info.kind == "target":
            data = self._portal_get(f"/_admin/records/{info.key}")
            records = list(data.values()) if isinstance(data, dict) else []
            return records, data is not None
        if info.kind == "source":
            data = self._portal_get("/_admin/events")
            events = (data or {}).get("events", []) if isinstance(data, dict) else []
            return events, data is not None
        return [], True

    def systems(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for info in SYSTEM_CATALOG:
            entry: dict[str, Any] = {
                "key": info.key,
                "display_name": info.display_name,
                "kind": info.kind,
                "role": info.role,
                "resource": info.resource,
                "operation": info.operation,
                "note": info.note,
            }
            if info.kind == "ai":
                classifications = [
                    {
                        "exception_id": e["exception_id"],
                        "employee_id": e["employee_id"],
                        "exception_type": e["exception_type"],
                        "field_name": e.get("field_name"),
                        "recommended_action": e.get("recommended_action"),
                        "ai_used": e.get("ai_used"),
                        "reason": e.get("reason"),
                        "status": e.get("status"),
                    }
                    for e in self.exceptions()
                ]
                entry.update(
                    {
                        "connected": self.chat_agent.enabled,
                        "enabled": self.chat_agent.enabled,
                        "mode": "openai" if self.chat_agent.enabled else "deterministic fallback",
                        "model": self.chat_agent.model if self.chat_agent.enabled else None,
                        "allowed_actions": sorted(ALLOWED_ACTIONS),
                        "records": classifications[:25],
                        "record_count": len(classifications),
                    }
                )
            elif info.kind == "orchestrator":
                entry.update({"connected": False, "records": [], "record_count": 0})
            else:
                records, connected = self._system_records(info)
                entry.update(
                    {
                        "connected": connected,
                        "records": records,
                        "record_count": len(records),
                    }
                )
            rows.append(entry)
        return rows

    def system(self, key: str) -> dict[str, Any] | None:
        for row in self.systems():
            if row["key"] == key:
                return row
        return None

    # -- read models -------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        exceptions = self.orchestrator.exceptions.all()
        open_count = sum(1 for e in exceptions if e.status == "OPEN")
        ledger = list(self.orchestrator.ledger.all().values())
        report = self.monitor.preview()
        review_pending = any(
            e.status == "OPEN" and e.recommended_action == "human_review"
            for e in exceptions
        )
        return {
            "open_exceptions": open_count,
            "resolved_exceptions": len(exceptions) - open_count,
            "human_review_pending": review_pending,
            "approaching_tasks": report.approaching,
            "overdue_tasks": report.overdue,
            "total_tasks": len(self.task_store.all()),
            "successful_operations": sum(
                1 for r in ledger if r.status == "SUCCESS"
            ),
            "skipped_operations": sum(
                1 for r in ledger if r.status == "SKIPPED_IDEMPOTENT"
            ),
            "failed_operations": sum(
                1
                for r in ledger
                if r.status not in ("SUCCESS", "SKIPPED_IDEMPOTENT")
            ),
            "ai_enabled": self.chat_agent.enabled,
        }

    def exceptions(self) -> list[dict[str, Any]]:
        rows = [e.to_dict() for e in self.orchestrator.exceptions.all()]
        rows.sort(key=lambda r: (r.get("status") != "OPEN", r.get("created_at") or ""))
        return rows

    def recent_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        entries = self.orchestrator.audit.read()
        entries.reverse()
        return entries[:limit]

    def tasks(self) -> list[dict[str, Any]]:
        rows = [t.to_dict() for t in self.task_store.all()]
        rows.sort(key=lambda r: r.get("due_date") or "")
        return rows

    def ledger(self) -> list[dict[str, Any]]:
        rows = [r.to_dict() for r in self.orchestrator.ledger.all().values()]
        rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return rows

    def monitor_view(self) -> dict[str, Any]:
        return self.monitor.preview().to_dict()

    def snapshot(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "open_exceptions": [
                r for r in self.exceptions() if r.get("status") == "OPEN"
            ],
            "recent_audit": self.recent_audit(limit=10),
            "tasks": self.tasks(),
            "monitor": self.monitor_view(),
            "ledger": self.ledger(),
        }

    # -- human-in-the-loop -------------------------------------------------
    def resolve_exception(
        self, exception_id: str, *, by: str, resolution: str
    ) -> dict[str, Any] | None:
        record = self.orchestrator.exceptions.resolve(
            exception_id, by=by, resolution=resolution
        )
        if record is None:
            return None
        self.orchestrator.audit.log_exception_resolution(record)
        return record.to_dict()

    # -- deadline monitor job ---------------------------------------------
    def run_monitor(self) -> dict[str, Any]:
        return self.monitor.run().to_dict()


    def write_portal(self, target: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Directly write to a demo portal target (bypasses the workflow)."""
        if not isinstance(payload, dict):
            return None
        try:
            from adapters.client import DemoPortalClient

            # ensure we have a client; if using in-process testclient, use it
            if self._test_client is not None:
                client = self._test_client
            else:
                client = self.portal.client
            employee_id = str(payload.get("employee_id", ""))
            if not employee_id:
                return None
            from app.targets import TARGET_SPECS

            spec = TARGET_SPECS.get(target)
            if spec is None:
                return None
            body = {
                "employee_id": employee_id,
                "event_id": payload.get("event_id"),
                "operation_key": payload.get("operation_key"),
                "data": payload.get("data", payload),
            }
            response = client.post(f"/{target}/{spec['resource']}", json=body)
            try:
                return response.json()
            except Exception:  # noqa: BLE001
                return {"status_code": response.status_code}
        except Exception:  # noqa: BLE001
            return None

    # -- demo reset --------------------------------------------------------
    def reset(self) -> dict[str, Any]:
        """Clear all demo state so scenarios can be re-run from scratch."""
        self._reset_portal()
        self.orchestrator.ledger.clear()
        self.orchestrator.exceptions.clear()
        self.orchestrator.audit.clear()
        self.task_store.reset()
        return {"status": "reset"}


def status_class(status: str) -> str:
    mapping = {
        OverallStatus.COMPLETED.value: "ok",
        OverallStatus.PARTIALLY_COMPLETED.value: "warn",
        OverallStatus.IN_PROGRESS.value: "info",
        OverallStatus.NEEDS_REVIEW.value: "warn",
        OverallStatus.FAILED.value: "err",
    }
    return mapping.get(status, "info")
