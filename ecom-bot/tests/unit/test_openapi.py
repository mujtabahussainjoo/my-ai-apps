"""OpenAPI contract tests: versioned paths and documented operations (FR-007, TASK-035)."""

from __future__ import annotations

from fastapi import FastAPI

_EXPECTED_PATHS = {
    "/health",
    "/ready",
    "/api/v1/chat",
    "/api/v1/conversations",
    "/api/v1/conversations/{conversation_id}",
    "/api/v1/documents",
    "/api/v1/documents/{document_id}",
    "/api/v1/feedback",
    "/api/v1/feedback/report",
    "/api/v1/tickets",
    "/api/v1/tickets/{ticket_id}",
    "/api/v1/tickets/{ticket_id}/refresh",
}


def test_openapi_exposes_versioned_endpoints(app: FastAPI) -> None:
    schema = app.openapi()
    assert _EXPECTED_PATHS.issubset(schema["paths"].keys())
    assert schema["info"]["title"] == "E-commerce AI Support Assistant"


def test_openapi_operations_have_summaries(app: FastAPI) -> None:
    schema = app.openapi()
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                assert operation.get("summary"), f"{method.upper()} {path} lacks a summary"
