"""FastAPI application factory.

The app is deliberately read-mostly. It exposes what the system currently
believes and lets an operator submit a backtest or a webhook; it never exposes
a route that places an order directly. Execution belongs to the trading loop,
which routes every order through the risk engine.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.core.config import get_settings
from src.core.enums import TradingMode
from src.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

DESCRIPTION = """
Read-mostly control plane for the trading system.

* Market data, signals, strategies, portfolio, trades and the full risk trail
* Backtest submission and results
* TradingView alert ingestion (recorded, never executed)

**No endpoint places an order.** Orders reach a venue only through the trading
loop and the risk engine.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "api_starting",
        mode=TradingMode(settings.trading_mode).value,
        live_trading_enabled=settings.live_trading_enabled,
    )
    yield
    logger.info("api_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title="my-financ API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )

    # The dashboard origin is an explicit allow-list; a wildcard would let any
    # page on the internet read this API from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Attach a request id and time the call.

        Errors are logged with the id and returned in the body, so a failure a
        user reports can be found in the logs without guessing which request it
        was.
        """
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            logger.exception(
                "request_failed",
                request_id=request_id,
                path=request.url.path,
                duration_ms=round(elapsed, 2),
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": "internal server error",
                    "request_id": request_id,
                },
            )
        elapsed = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-ms"] = f"{elapsed:.2f}"
        return response

    from apps.api.routes import (
        agents,
        backtest,
        control,
        health,
        market,
        metrics,
        portfolio,
        strategies,
        tradingview,
    )

    # metrics last: it is the only router that is not part of the documented
    # surface, and it must not shadow /health.
    for module in (health, market, strategies, portfolio, backtest, tradingview, metrics, agents, control):
        app.include_router(module.router)

    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    dashboard = Path(__file__).resolve().parents[1] / "dashboard" / "static"
    app.mount("/dashboard", StaticFiles(directory=dashboard, html=True), name="dashboard")

    @app.get("/", tags=["meta"])
    def root() -> dict[str, object]:
        return {
            "service": "my-financ API",
            "version": app.version,
            "docs": "/docs",
            "dashboard": "/dashboard/",
            "mode": TradingMode(settings.trading_mode).value,
            "live_trading_enabled": settings.live_trading_enabled,
            "routes": sorted({r.path for r in app.routes if getattr(r, "path", "").startswith("/")}),
        }

    return app


app = create_app()

__all__ = ["app", "create_app", "lifespan"]
