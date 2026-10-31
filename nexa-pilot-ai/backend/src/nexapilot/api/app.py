"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import secrets as secrets_module
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nexapilot import __version__
from nexapilot.api.routes_accounts import router as accounts_router
from nexapilot.api.routes_chat import router as chat_router
from nexapilot.api.routes_settings import router as settings_router
from nexapilot.api.routes_tools import router as tools_router
from nexapilot.api.routes_workspace import router as workspace_router
from nexapilot.core.config import Settings, get_settings
from nexapilot.core.container import Container
from nexapilot.core.errors import NexaPilotError
from nexapilot.core.logging import configure_logging, get_logger

log = get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    container: Container | None = None,
    *,
    initialize_db: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> Any:
        active_container = container or Container.create(settings)
        app.state.container = active_container
        app.state.registry = _build_registry()
        app.state.active_runs = {}
        app.state.oauth_states = {}
        app.state.checkpoint_saver = None
        if initialize_db:
            await asyncio.to_thread(_initialize_database, settings)
        app.state.checkpoint_saver = await _create_checkpointer(settings)
        app.state.graph = _build_graph(app.state.checkpoint_saver)
        try:
            yield
        finally:
            saver = app.state.checkpoint_saver
            if saver is not None:
                await saver.conn.close()
            active_container.dispose()

    app = FastAPI(
        title="NexaPilot AI",
        version=__version__,
        description="Local-first desktop personal AI assistant.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_api_token(request: Request, call_next: Any) -> Any:
        """Enforce the optional shared token; the API can act on the user's behalf."""
        token = settings.api_token
        skip = request.method == "OPTIONS" or request.url.path in {
            "/api/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        }
        if token and not skip:
            header = request.headers.get("authorization", "")
            if not secrets_module.compare_digest(header, f"Bearer {token}"):
                return JSONResponse(
                    status_code=401,
                    content={
                        "code": "unauthorized",
                        "message": "A valid API token is required.",
                        "retryable": False,
                        "details": {},
                        "setup_hint": "",
                    },
                )
        return await call_next(request)

    @app.exception_handler(NexaPilotError)
    async def handle_nexapilot_error(_request: Request, exc: NexaPilotError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        active: Container = request.app.state.container
        from nexapilot.services.provider_settings import get_active_config

        session = active.session_factory()
        try:
            config = get_active_config(session)
        finally:
            session.close()
        return {
            "status": "ok",
            "version": __version__,
            "active_provider": config.provider if config else None,
            "active_model": config.model if config else None,
            "environment": settings.environment,
        }

    app.include_router(settings_router)
    app.include_router(chat_router)
    app.include_router(accounts_router)
    app.include_router(workspace_router)
    app.include_router(tools_router)
    return app


def _build_registry() -> Any:
    from nexapilot.tools.registry import build_default_registry

    return build_default_registry()


def _build_graph(checkpointer: Any = None) -> Any:
    from nexapilot.agents.graph import build_graph

    return build_graph(checkpointer=checkpointer)


async def _create_checkpointer(settings: Settings) -> Any:
    """Persist LangGraph checkpoints in SQLite so runs survive a restart."""
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from nexapilot.core.paths import data_dir

        path = data_dir() / "checkpoints.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(path)
        saver = AsyncSqliteSaver(connection)
        await saver.setup()
        return saver
    except Exception as exc:
        log.warning("checkpoint.disabled", error=type(exc).__name__)
        return None


def _initialize_database(settings: Settings) -> None:
    from nexapilot.db.base import initialize_database

    try:
        initialize_database(settings)
    except Exception as exc:
        log.warning("database.initialization_failed", error=type(exc).__name__)


app = create_app()
