"""HTTP-level chat streaming through the real FastAPI app."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexapilot.providers.base import (
    ChatRequest,
    ConnectionTestResult,
    StreamEvent,
    TokenUsage,
    ToolCall,
)


class ScriptedProvider:
    provider_id = "scripted"
    model = "scripted-1"
    requires_api_key = False

    def __init__(self, answer: str = "Hello from the scripted model.") -> None:
        self.answer = answer

    async def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(ok=True, provider=self.provider_id, model=self.model)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        for chunk in self.answer.split(" "):
            yield StreamEvent(type="text", text=f"{chunk} ")
        yield StreamEvent(type="usage", usage=TokenUsage(input_tokens=1, output_tokens=1))


def _sse_events(response_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for frame in response_text.split("\n\n"):
        frame = frame.strip()
        if frame.startswith("data:"):
            events.append(json.loads(frame[5:].strip()))
    return events


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> ScriptedProvider:
    from nexapilot.services import provider_settings

    provider = ScriptedProvider()
    monkeypatch.setattr(provider_settings, "get_active_provider", lambda session, secrets: provider)
    return provider


def test_chat_streams_tokens_and_persists(client: TestClient, scripted: ScriptedProvider) -> None:
    response = client.post("/api/chat", json={"message": "Say hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _sse_events(response.text)
    types = [event["type"] for event in events]
    assert "token" in types
    assert types[-1] == "done"
    done = events[-1]
    assert done["status"] == "completed"
    assert "scripted" in done["answer"].lower()
    assert done["provider"] == "scripted"

    conversation_id = done["conversation_id"]
    messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
    roles = [message["role"] for message in messages]
    assert roles == ["user", "assistant"]
    assert messages[1]["model"] == "scripted-1"

    activity = client.get("/api/activity").json()
    assert activity[0]["workflow"] == "general"
    assert activity[0]["status"] == "completed"


def test_chat_routes_an_email_request(client: TestClient, scripted: ScriptedProvider) -> None:
    response = client.post("/api/chat", json={"message": "Summarise my unread email"})
    events = _sse_events(response.text)
    routing = next(event for event in events if event["type"] == "routing")
    assert routing["workflow"] == "email"


def test_chat_without_provider_reports_actionable_error(client: TestClient) -> None:
    response = client.post("/api/chat", json={"message": "hello"})
    events = _sse_events(response.text)
    assert events[0]["type"] == "error"
    assert events[0]["code"] == "configuration_error"
    activity = client.get("/api/activity").json()
    assert activity[0]["status"] == "failed"


def test_tool_endpoint_gates_side_effects(client: TestClient) -> None:
    first = client.post(
        "/api/tools/send_email",
        json={
            "arguments": {
                "to": ["person@example.com"],
                "subject": "Hi",
                "body": "Body",
            }
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "approval_required"
    approval_id = body["approval"]["id"]

    pending = client.get("/api/approvals?status=pending").json()
    assert [item["id"] for item in pending] == [approval_id]

    rejected = client.post(
        f"/api/tools/send_email/approvals/{approval_id}", json={"approved": False}
    )
    assert rejected.json()["status"] == "rejected"

    again = client.post(
        "/api/tools/send_email",
        json={"arguments": {"to": ["person@example.com"], "subject": "Hi", "body": "Body"}},
    )
    assert again.json()["status"] == "approval_required"
    assert again.json()["approval"]["id"] != approval_id


def test_unknown_tool_is_404(client: TestClient) -> None:
    response = client.post("/api/tools/does_not_exist", json={"arguments": {}})
    assert response.status_code == 404


def test_tool_argument_validation(client: TestClient) -> None:
    response = client.post("/api/tools/send_email", json={"arguments": {"to": []}})
    assert response.status_code == 422


def test_openapi_lists_expected_routes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    for path in ("/api/chat", "/api/tools/{tool_name}", "/api/providers/active", "/api/health"):
        assert path in paths


def test_tool_call_emits_approval_event(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    from nexapilot.services import provider_settings

    class ToolCallingProvider(ScriptedProvider):
        async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
            yield StreamEvent(
                type="tool_call",
                tool_call=ToolCall(
                    id="c1",
                    name="send_email",
                    arguments={"to": ["a@example.com"], "subject": "s", "body": "b"},
                ),
            )

    monkeypatch.setattr(
        provider_settings,
        "get_active_provider",
        lambda session, secrets: ToolCallingProvider(),
    )
    response = client.post("/api/chat", json={"message": "Send an email to a@example.com"})
    events = _sse_events(response.text)
    approvals = [event for event in events if event["type"] == "approval_required"]
    assert approvals
    assert approvals[0]["approval"]["action"] == "email.send"
    done = events[-1]
    assert done["status"] == "awaiting_approval"


class SlowProvider(ScriptedProvider):
    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        import asyncio

        for index in range(200):
            await asyncio.sleep(0.005)
            yield StreamEvent(type="text", text=f"{index} ")


async def test_cancel_stops_the_run(monkeypatch: pytest.MonkeyPatch, container: Any) -> None:
    import asyncio

    from nexapilot.agents.graph import build_graph
    from nexapilot.services import provider_settings
    from nexapilot.services.chat_service import ChatInput, ChatService
    from nexapilot.tools.registry import build_default_registry

    monkeypatch.setattr(
        provider_settings, "get_active_provider", lambda session, secrets: SlowProvider()
    )
    service = ChatService(container, build_default_registry(), build_graph())
    session = container.session_factory()
    cancel = asyncio.Event()
    events: list[dict[str, Any]] = []
    stream = service.run_chat(session, ChatInput(message="count please"), cancel_event=cancel)
    try:
        async for event in stream:
            events.append(event)
            if event["type"] == "token":
                cancel.set()
    except asyncio.CancelledError:
        pass
    finally:
        await stream.aclose()
        session.close()

    types = [event["type"] for event in events]
    assert "cancelled" in types
    assert "done" not in types
