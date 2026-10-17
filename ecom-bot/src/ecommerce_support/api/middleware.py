"""Request correlation middleware (pure ASGI so contextvars reach endpoint code)."""

from __future__ import annotations

import time
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ecommerce_support.core.observability import request_context

REQUEST_ID_HEADER = "X-Request-ID"
PROCESS_TIME_HEADER = "X-Process-Time"


class RequestContextMiddleware:
    """Assigns a correlation id, exposes it via contextvars/request.state, and adds timing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        started = time.perf_counter()

        with request_context(request_id=incoming) as request_id:
            state: dict[str, Any] = scope.setdefault("state", {})
            state["request_id"] = request_id

            async def send_wrapper(message: Message) -> None:
                if message["type"] == "http.response.start":
                    elapsed = time.perf_counter() - started
                    headers = MutableHeaders(scope=message)
                    headers[REQUEST_ID_HEADER] = request_id
                    headers[PROCESS_TIME_HEADER] = f"{elapsed:.4f}"
                await send(message)

            await self.app(scope, receive, send_wrapper)


def add_request_context_middleware(app: Any) -> None:
    """Register :class:`RequestContextMiddleware` on a FastAPI/Starlette app."""
    app.add_middleware(RequestContextMiddleware)


__all__ = [
    "PROCESS_TIME_HEADER",
    "REQUEST_ID_HEADER",
    "RequestContextMiddleware",
    "add_request_context_middleware",
]
