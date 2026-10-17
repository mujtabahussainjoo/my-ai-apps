"""FastAPI application factory and entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ecommerce_support import __version__
from ecommerce_support.api.middleware import add_request_context_middleware
from ecommerce_support.api.routes import health
from ecommerce_support.core.config import Settings, get_settings
from ecommerce_support.core.exceptions import AppError
from ecommerce_support.core.logging import configure_logging, get_logger
from ecommerce_support.core.observability import current_request_id
from ecommerce_support.core.readiness import register_readiness_check

# Importing db.session registers the database readiness check (idempotent).
from ecommerce_support.db.session import check_database, close_engine

_log = get_logger(__name__)

register_readiness_check(check_database)


def _error_payload(request: Request, exc: AppError) -> dict[str, Any]:
    return {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "retryable": exc.retryable,
        },
        "request_id": current_request_id() or getattr(request.state, "request_id", None),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    log = get_logger("ecommerce_support.app")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        log.info("startup", **settings.security_summary())
        try:
            yield
        finally:
            await close_engine()
            log.info("shutdown")

    app = FastAPI(
        title="E-commerce AI Support Assistant",
        version=__version__,
        description="Multi-agent (LangGraph) RAG support chatbot with streaming and escalation.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    add_request_context_middleware(app)

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        log.warning(
            "app_error",
            error_code=exc.code,
            http_status=exc.http_status,
            path=request.url.path,
        )
        return JSONResponse(status_code=exc.http_status, content=_error_payload(request, exc))

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.error(
            "unhandled_error",
            path=request.url.path,
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "details": {},
                    "retryable": False,
                },
                "request_id": current_request_id() or getattr(request.state, "request_id", None),
            },
        )

    app.include_router(health.router)
    return app


app = create_app()
