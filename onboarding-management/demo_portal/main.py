"""Local demo portal: a single FastAPI app that simulates every
third-party system the onboarding workflow talks to.

Run it with::

    python -m demo_portal.main

or::

    uvicorn demo_portal.main:app --host 127.0.0.1 --port 8088

Each target exposes a write endpoint (upsert) and a read endpoint the
orchestrator uses to *verify* the result independently.

Fault injection is available via ``POST /_admin/faults`` so tests and the
demo can simulate temporary failures, rate limits, permanent rejections
and timeouts with an unknown outcome.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.targets import TARGET_SPECS
from demo_portal.store import (
    PERMANENT,
    RATE_LIMIT,
    STORE,
    TEMPORARY,
    TIMEOUT,
    VALID_MODES,
    FaultRule,
)

app = FastAPI(title="BetterUp Onboarding - Local Demo Portal", version="0.1.0")


class WriteRequest(BaseModel):
    employee_id: str
    event_id: str | None = None
    operation_key: str | None = None
    data: dict[str, Any] = {}


class WriteResponse(BaseModel):
    status: str
    target: str
    operation: str
    employee_id: str
    duplicate: bool = False


class FaultRequest(BaseModel):
    target: str = "*"
    operation: str = "*"
    mode: str = "success"
    remaining: int = -1


def _apply(target: str, req: WriteRequest) -> None:
    payload: dict[str, Any] = dict(req.data)
    payload["employee_id"] = req.employee_id
    if req.event_id:
        payload["event_id"] = req.event_id
    if req.operation_key:
        payload["operation_key"] = req.operation_key
    STORE.upsert(target, req.employee_id, payload)


def _write(target: str, operation: str, req: WriteRequest) -> WriteResponse:
    mode = STORE.next_fault(target, operation)

    # Failures that must NOT change state: safe to retry / escalate.
    if mode in (TEMPORARY, RATE_LIMIT, PERMANENT):
        status = {TEMPORARY: 503, RATE_LIMIT: 429, PERMANENT: 400}[mode]
        raise HTTPException(status_code=status, detail=f"simulated {mode} failure")

    duplicate = not STORE.note_operation_key(req.operation_key)
    if not duplicate:
        _apply(target, req)

    # Timeout = target may have applied the change but did not acknowledge.
    if mode == TIMEOUT:
        raise HTTPException(
            status_code=504, detail="simulated timeout (outcome unknown)"
        )

    return WriteResponse(
        status="SUCCESS",
        target=target,
        operation=operation,
        employee_id=req.employee_id,
        duplicate=duplicate,
    )


def _register_target(target: str, resource: str, operation: str) -> None:
    def write_endpoint(req: WriteRequest) -> WriteResponse:
        return _write(target, operation, req)

    def read_endpoint(employee_id: str) -> dict[str, Any]:
        record = STORE.get(target, employee_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"{target} has no record for {employee_id}"
            )
        return {"target": target, "employee_id": employee_id, "record": record}

    write_endpoint.__name__ = f"write_{target}"
    read_endpoint.__name__ = f"read_{target}"
    app.post(f"/{target}/{resource}", response_model=WriteResponse)(write_endpoint)
    app.get(f"/{target}/{resource}/{{employee_id}}")(read_endpoint)


for _target, _spec in TARGET_SPECS.items():
    _register_target(_target, _spec["resource"], _spec["operation"])


# -- Ashby is an event *source*, not a propagation target --------------------
class AshbyEvent(BaseModel):
    event_id: str
    source: str = "ashby"
    employee_id: str
    event_type: str = "employee_updated"
    changed_fields: list[str] = []
    approved: bool = True
    received_at: str | None = None
    employee: dict[str, Any] = {}


@app.post("/ashby/events")
def seed_ashby_event(payload: AshbyEvent) -> dict[str, Any]:
    STORE.events[payload.event_id] = payload.model_dump()
    return {"status": "stored", "event_id": payload.event_id}


@app.get("/ashby/events/{event_id}")
def get_ashby_event(event_id: str) -> dict[str, Any]:
    event = STORE.events.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return event


# -- admin / fault injection -------------------------------------------------
@app.post("/_admin/faults")
def add_fault(req: FaultRequest) -> dict[str, Any]:
    if req.mode not in VALID_MODES:
        raise HTTPException(status_code=400, detail=f"unknown mode '{req.mode}'")
    STORE.faults.append(FaultRule(req.target, req.operation, req.mode, req.remaining))
    return {"status": "ok", "faults": [f.__dict__ for f in STORE.faults]}


@app.post("/_admin/reset")
def reset() -> dict[str, str]:
    STORE.reset()
    return {"status": "reset"}


@app.get("/_admin/state")
def state() -> dict[str, Any]:
    return {
        "targets": {t: len(STORE.all(t)) for t in TARGET_SPECS},
        "applied_keys": len(STORE.applied_keys),
        "faults": [f.__dict__ for f in STORE.faults],
    }


@app.get("/_admin/records/{target}")
def admin_records(target: str) -> dict[str, Any]:
    return STORE.all(target)


@app.get("/_admin/events")
def admin_events() -> dict[str, Any]:
    return {"events": list(STORE.events.values())}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    from app.config import settings

    uvicorn.run(
        "demo_portal.main:app",
        host=settings.demo_portal_host,
        port=settings.demo_portal_port,
        reload=False,
    )
