"""Shared pytest fixtures.

The demo portal runs in-process via Starlette's ``TestClient`` so tests
need no network. Every store uses an isolated ``tmp_path`` so tests never
share state or touch the real ``data/`` files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.client import DemoPortalClient
from app.ai_helper import AIHelper
from app.audit_logger import AuditLogger
from app.exception_handler import ExceptionHandler
from app.idempotency_store import IdempotencyStore
from app.orchestrator import Orchestrator
from app.retry_handler import RetryHandler
from demo_portal.main import app

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_events"


@pytest.fixture
def portal():
    test_client = TestClient(app)
    test_client.post("/_admin/reset")
    client = DemoPortalClient(base_url="http://testserver", client=test_client)
    yield client
    test_client.post("/_admin/reset")


@pytest.fixture
def sample_event():
    def _load(name: str):
        return json.loads((SAMPLE_DIR / name).read_text())

    return _load


@pytest.fixture
def make_orchestrator(portal, tmp_path):
    def _make(
        *,
        ai: AIHelper | None = None,
        max_retries: int = 3,
        portal_client: DemoPortalClient | None = None,
    ) -> Orchestrator:
        return Orchestrator(
            portal=portal_client or portal,
            ledger=IdempotencyStore(path=tmp_path / "ledger.json"),
            exception_handler=ExceptionHandler(path=tmp_path / "exceptions.json"),
            audit=AuditLogger(path=tmp_path / "audit.jsonl"),
            retry_handler=RetryHandler(
                max_retries=max_retries, base_delay=0, sleep=lambda _: None
            ),
            ai=ai or AIHelper(api_key=""),
        )

    return _make
