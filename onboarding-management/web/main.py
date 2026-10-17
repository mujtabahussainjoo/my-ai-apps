"""FastAPI dashboard (server-rendered) + JSON APIs + chat agent.

Run it with::

    python -m web.main
    # or
    uvicorn web.main:app --host 127.0.0.1 --port 8090

Open http://127.0.0.1:8090/ for the dashboard. By default the demo portal
runs in-process, so no second server is required. Set ``WEB_LIVE=1`` to
talk to a separately-running demo portal at ``DEMO_PORTAL_URL``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from web.state import WebState

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []


class ResolveRequest(BaseModel):
    by: str = "operator"
    resolution: str = ""


def _live_from_env() -> bool:
    return os.getenv("WEB_LIVE", "").lower() in {"1", "true", "yes", "on"}


def create_app(state: WebState | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "web", None) is None:
            app.state.web = WebState(live=_live_from_env())
        yield

    app = FastAPI(
        title="BetterUp Onboarding - Dashboard",
        version="0.1.0",
        lifespan=lifespan,
    )
    if state is not None:
        app.state.web = state

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    def get_state(request: Request) -> WebState:
        web = getattr(request.app.state, "web", None)
        if web is None:  # pragma: no cover - only if lifespan was skipped
            raise HTTPException(status_code=503, detail="dashboard not ready")
        return web

    # -- pages -------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        web = get_state(request)
        systems = web.systems()
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "scenarios": list(web.scenarios.values()),
                "systems": systems,
                "sys_names": {s["key"]: s["display_name"] for s in systems},
                "ai_enabled": web.chat_agent.enabled,
                "live": web.live,
            },
        )

    @app.get("/api/systems")
    def api_systems(request: Request) -> dict:
        return {"systems": get_state(request).systems()}

    @app.get("/api/systems/{key}")
    def api_system(key: str, request: Request) -> dict:
        system = get_state(request).system(key)
        if system is None:
            raise HTTPException(status_code=404, detail=f"unknown system '{key}'")
        return system

    # -- read APIs ---------------------------------------------------------
    @app.get("/api/summary")
    def api_summary(request: Request) -> dict:
        return get_state(request).summary()

    @app.get("/api/exceptions")
    def api_exceptions(request: Request) -> dict:
        return {"exceptions": get_state(request).exceptions()}

    @app.get("/api/audit")
    def api_audit(request: Request, limit: int = 50) -> dict:
        return {"entries": get_state(request).recent_audit(limit=limit)}

    @app.get("/api/tasks")
    def api_tasks(request: Request) -> dict:
        web = get_state(request)
        return {"tasks": web.tasks(), "monitor": web.monitor_view()}

    @app.get("/api/ledger")
    def api_ledger(request: Request) -> dict:
        return {"ledger": get_state(request).ledger()}

    # -- actions -----------------------------------------------------------
    @app.post("/api/scenarios/{key}")
    def api_run_scenario(key: str, request: Request) -> dict:
        web = get_state(request)
        try:
            result = web.run_scenario(key)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown scenario '{key}'")
        return result.to_dict()

    @app.post("/api/exceptions/{exception_id}/resolve")
    def api_resolve(
        exception_id: str, payload: ResolveRequest, request: Request
    ) -> dict:
        web = get_state(request)
        record = web.resolve_exception(
            exception_id, by=payload.by, resolution=payload.resolution
        )
        if record is None:
            raise HTTPException(status_code=404, detail="exception not found")
        return record

    @app.post("/api/monitor/run")
    def api_monitor_run(request: Request) -> dict:
        return get_state(request).run_monitor()

    @app.post("/api/reset")
    def api_reset(request: Request) -> dict:
        return get_state(request).reset()

    @app.post("/api/ingest/event")
    def api_ingest_event(payload: dict, request: Request) -> dict:
        web = get_state(request)
        try:
            result = web.orchestrator.handle(payload)
            return result.to_dict()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/portals/{target}/write")
    def api_portal_write(target: str, payload: dict, request: Request) -> dict:
        web = get_state(request)
        try:
            res = web.write_portal(target, payload)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc))
        if res is None:
            raise HTTPException(status_code=404, detail=f"unknown target or write failed")
        return res

    @app.get("/api/portals/events")
    def api_portal_events(request: Request) -> dict:
        data = get_state(request)._portal_get("/_admin/events")
        if data is None:
            return {"events": []}
        return data

    @app.post("/api/chat")
    def api_chat(payload: ChatRequest, request: Request) -> dict:
        from app.chat_agent import ChatMessage

        web = get_state(request)
        history = [ChatMessage(role=t.role, content=t.content) for t in payload.history]
        response = web.chat_agent.respond(
            payload.message, snapshot=web.snapshot(), history=history
        )
        return response.to_dict()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    from app.config import settings

    print(f"Dashboard: http://{settings.web_host}:{settings.web_port}/  (Ctrl+C to quit)")
    uvicorn.run(
        "web.main:app",
        host=settings.web_host,
        port=settings.web_port,
        reload=False,
    )
