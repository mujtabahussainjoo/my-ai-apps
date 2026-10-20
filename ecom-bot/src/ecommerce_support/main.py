"""FastAPI application factory and entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ecommerce_support import __version__
from ecommerce_support.api.middleware import add_request_context_middleware
from ecommerce_support.api.routes import (
    chat,
    conversations,
    documents,
    feedback,
    health,
    metrics,
    tickets,
)
from ecommerce_support.core.config import Settings, get_settings
from ecommerce_support.core.exceptions import AppError, AuthenticationError
from ecommerce_support.core.logging import configure_logging, get_logger
from ecommerce_support.core.observability import current_request_id
from ecommerce_support.core.readiness import register_readiness_check
from ecommerce_support.core.tracing import configure_tracing

# Importing db.session registers the database readiness check (idempotent).
from ecommerce_support.db.session import check_database, close_engine

# Embedding dimension validation runs as part of readiness (FR-036).
from ecommerce_support.rag.embeddings.factory import check_embedding_dimensions

_log = get_logger(__name__)

register_readiness_check(check_database)
register_readiness_check(check_embedding_dimensions)


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


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Reduce validation errors to non-sensitive fields (never echo the rejected input)."""
    return [
        {
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": str(error.get("msg", "invalid value")),
            "type": str(error.get("type", "value_error")),
        }
        for error in exc.errors()
    ]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    log = get_logger("ecommerce_support.app")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure_tracing(settings)
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
        headers = dict(exc.headers)
        if isinstance(exc, AuthenticationError):
            headers.setdefault("WWW-Authenticate", "Bearer")
        return JSONResponse(
            status_code=exc.http_status, content=_error_payload(request, exc), headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Normalize FastAPI's validation error to the single error envelope (safe fields only).
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request could not be processed.",
                    "details": {"errors": _safe_validation_errors(exc)},
                    "retryable": False,
                },
                "request_id": current_request_id() or getattr(request.state, "request_id", None),
            },
        )

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
    app.include_router(metrics.router)
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(documents.router)
    app.include_router(feedback.router)
    app.include_router(tickets.router)
    return app


app = create_app()
