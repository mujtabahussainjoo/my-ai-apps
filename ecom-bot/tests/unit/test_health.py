"""Tests for health/readiness endpoints, correlation ids, and error handling."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import AsyncClient

from ecommerce_support.api.middleware import REQUEST_ID_HEADER
from ecommerce_support.api.routes.health import CheckResult, register_readiness_check
from ecommerce_support.core.exceptions import AuthorizationError


async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


async def test_ready_ok(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["config"]["ok"] is True


async def test_ready_failure_returns_503(client: AsyncClient) -> None:
    async def failing_check() -> CheckResult:
        return CheckResult("database", False, "connection refused")

    failing_check.__name__ = "database"
    register_readiness_check(failing_check)
    response = await client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["ok"] is False


async def test_request_id_is_generated_and_echoed(client: AsyncClient) -> None:
    generated = await client.get("/health")
    assert generated.headers[REQUEST_ID_HEADER].startswith("req_")

    echoed = await client.get("/health", headers={REQUEST_ID_HEADER: "req_abc123"})
    assert echoed.headers[REQUEST_ID_HEADER] == "req_abc123"


async def test_process_time_header_present(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert float(response.headers["X-Process-Time"]) >= 0.0


async def test_app_error_handler_returns_safe_payload(app: FastAPI) -> None:
    @app.get("/boom")
    async def boom() -> None:  # pragma: no cover - exercised via client below
        raise AuthorizationError("You may not access this order.")

    from httpx import ASGITransport

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        response = await http_client.get("/boom")
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "forbidden"
    assert "Traceback" not in response.text


async def test_unhandled_error_is_sanitized(app: FastAPI) -> None:
    @app.get("/kaboom")
    async def kaboom() -> None:  # pragma: no cover - exercised via client below
        raise RuntimeError("internal detail that must not leak")

    from httpx import ASGITransport

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        response = await http_client.get("/kaboom")
    assert response.status_code == 500
    assert "internal detail" not in response.text
    assert response.json()["error"]["code"] == "internal_error"
