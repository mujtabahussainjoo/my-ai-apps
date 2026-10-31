"""End-to-end approval gate tests using a scripted provider."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select

from nexapilot.agents.llm_loop import run_agent_turn
from nexapilot.agents.permissions import EMAIL_MODIFY, EMAIL_READ, EMAIL_SEND
from nexapilot.core.container import Container
from nexapilot.db.models import ApprovalRequest
from nexapilot.providers.base import ChatRequest, StreamEvent, TokenUsage, ToolCall
from nexapilot.tools.base import ToolContext
from nexapilot.tools.registry import build_default_registry


class ScriptedProvider:
    """Yields a fixed sequence of events, then stops."""

    provider_id = "scripted"
    model = "scripted-1"
    requires_api_key = False

    def __init__(self, tool_calls: list[ToolCall]) -> None:
        self.tool_calls = tool_calls
        self.requests: list[ChatRequest] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if len(self.requests) > 1:
            yield StreamEvent(type="text", text="Done.")
            return
        for call in self.tool_calls:
            yield StreamEvent(type="tool_call", tool_call=call)
        yield StreamEvent(type="usage", usage=TokenUsage(input_tokens=1, output_tokens=1))


def _ctx(container: Container, session: Any) -> ToolContext:
    return ToolContext(
        container=container,
        session=session,
        task_run_id="run-1",
        conversation_id="conv-1",
        granted_permissions=frozenset({EMAIL_READ, EMAIL_SEND, EMAIL_MODIFY}),
    )


async def test_side_effecting_tool_stops_for_approval(container: Container) -> None:
    registry = build_default_registry()
    provider = ScriptedProvider(
        [
            ToolCall(
                id="call-1",
                name="send_email",
                arguments={
                    "to": ["person@example.com"],
                    "subject": "Hello",
                    "body": "Body",
                },
            )
        ]
    )
    session = container.session_factory()
    try:
        result = await run_agent_turn(
            provider,
            messages=[{"role": "user", "content": "Send an email"}],
            tools=registry.definitions(["send_email"]),
            registry=registry,
            ctx=_ctx(container, session),
        )
        session.commit()
        assert result.pending_approval is not None
        assert result.pending_approval["action"] == "email.send"
        assert result.tool_calls_made == [], "the tool must not run before approval"

        requests = list(session.scalars(select(ApprovalRequest)))
        assert len(requests) == 1
        assert requests[0].status == "pending"
        assert requests[0].payload["tool"] == "send_email"
        assert len(provider.requests) == 1, "the agent stops instead of looping"
    finally:
        session.close()


async def test_approval_is_scoped_to_one_action(container: Container) -> None:
    """An approval for email.send must not authorise email.delete."""
    from nexapilot.services import approvals

    registry = build_default_registry()
    session = container.session_factory()
    try:
        request = approvals.create_request(
            session, action="email.send", title="Send", task_run_id="run-1"
        )
        approvals.decide(session, request.id, approved=True)

        provider = ScriptedProvider(
            [ToolCall(id="call-2", name="delete_email", arguments={"message_id": "m1"})]
        )
        result = await run_agent_turn(
            provider,
            messages=[{"role": "user", "content": "Delete it"}],
            tools=registry.definitions(["delete_email"]),
            registry=registry,
            ctx=_ctx(container, session),
            approved_actions={"email.send": request.id},
        )
        session.commit()
        assert result.pending_approval is not None
        assert result.pending_approval["action"] == "email.delete"
    finally:
        session.close()


async def test_approved_action_passes_the_gate(container: Container) -> None:
    from nexapilot.services import approvals

    registry = build_default_registry()
    session = container.session_factory()
    try:
        request = approvals.create_request(
            session, action="email.send", title="Send", task_run_id="run-1"
        )
        approvals.decide(session, request.id, approved=True)

        provider = ScriptedProvider(
            [
                ToolCall(
                    id="call-3",
                    name="send_email",
                    arguments={"to": ["a@example.com"], "subject": "s", "body": "b"},
                )
            ]
        )
        result = await run_agent_turn(
            provider,
            messages=[{"role": "user", "content": "Send it"}],
            tools=registry.definitions(["send_email"]),
            registry=registry,
            ctx=_ctx(container, session),
            approved_actions={"email.send": request.id},
        )
        session.commit()
        # The gate opened: the tool ran and failed only because no account exists.
        assert result.pending_approval is None
        assert result.tool_calls_made
        assert result.tool_calls_made[0]["status"] == "error"
        assert "account" in result.tool_calls_made[0]["error"].lower()
    finally:
        session.close()


async def test_rejected_approval_does_not_run(container: Container) -> None:
    from nexapilot.services import approvals

    registry = build_default_registry()
    session = container.session_factory()
    try:
        request = approvals.create_request(
            session, action="email.send", title="Send", task_run_id="run-1"
        )
        approvals.decide(session, request.id, approved=False)

        provider = ScriptedProvider(
            [
                ToolCall(
                    id="call-4",
                    name="send_email",
                    arguments={"to": ["a@example.com"], "subject": "s", "body": "b"},
                )
            ]
        )
        result = await run_agent_turn(
            provider,
            messages=[{"role": "user", "content": "Send it"}],
            tools=registry.definitions(["send_email"]),
            registry=registry,
            ctx=_ctx(container, session),
            approved_actions={"email.send": request.id},
        )
        session.commit()
        assert result.pending_approval is not None
        assert result.pending_approval["status"] == "rejected"
        assert result.tool_calls_made == []
    finally:
        session.close()


async def test_writes_outside_workspace_blocked_before_execution(
    container: Container, tmp_path: Any
) -> None:
    from nexapilot.agents.permissions import FS_READ, FS_WRITE

    registry = build_default_registry()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    container.settings.coding_workspace_root = str(workspace)
    session = container.session_factory()
    try:
        provider = ScriptedProvider(
            [
                ToolCall(
                    id="call-5",
                    name="write_file",
                    arguments={"path": "../../etc/passwd", "content": "x"},
                )
            ]
        )
        ctx = ToolContext(
            container=container,
            session=session,
            granted_permissions=frozenset({FS_READ, FS_WRITE}),
        )
        result = await run_agent_turn(
            provider,
            messages=[{"role": "user", "content": "write"}],
            tools=registry.definitions(["write_file"]),
            registry=registry,
            ctx=ctx,
        )
        assert result.tool_calls_made[0]["status"] == "error"
        assert "outside" in result.tool_calls_made[0]["error"].lower()
    finally:
        session.close()


async def test_audit_trail_records_decisions_and_tool_runs(container: Container) -> None:
    from nexapilot.db.models import AuditLog
    from nexapilot.services import approvals

    registry = build_default_registry()
    session = container.session_factory()
    try:
        request = approvals.create_request(
            session, action="email.send", title="Send", task_run_id="run-1"
        )
        approvals.decide(session, request.id, approved=True)

        provider = ScriptedProvider(
            [
                ToolCall(
                    id="call-audit",
                    name="send_email",
                    arguments={
                        "to": ["a@example.com"],
                        "subject": "s",
                        "body": "do not log this body",
                    },
                )
            ]
        )
        await run_agent_turn(
            provider,
            messages=[{"role": "user", "content": "Send it"}],
            tools=registry.definitions(["send_email"]),
            registry=registry,
            ctx=_ctx(container, session),
            approved_actions={"email.send": request.id},
        )
        session.commit()

        rows = list(session.scalars(select(AuditLog)))
        actions = {row.action for row in rows}
        assert "approval.approved" in actions
        assert "tool.send_email" in actions
        serialized = " ".join(str(row.details) for row in rows)
        assert "do not log this body" not in serialized
        assert "a@example.com" not in serialized
    finally:
        session.close()


async def test_invalid_arguments_do_not_create_an_approval(container: Container) -> None:
    from nexapilot.agents.permissions import CALENDAR_READ, CALENDAR_WRITE

    registry = build_default_registry()
    provider = ScriptedProvider(
        [
            ToolCall(
                id="call-invalid",
                name="create_event",
                arguments={"title": "", "start_at": "not-a-date"},
            )
        ]
    )
    session = container.session_factory()
    try:
        ctx = ToolContext(
            container=container,
            session=session,
            task_run_id="run-1",
            granted_permissions=frozenset({CALENDAR_READ, CALENDAR_WRITE}),
        )
        result = await run_agent_turn(
            provider,
            messages=[{"role": "user", "content": "Create it"}],
            tools=registry.definitions(["create_event"]),
            registry=registry,
            ctx=ctx,
        )
        session.commit()
        assert result.pending_approval is None
        assert result.tool_calls_made
        assert result.tool_calls_made[0]["code"] == "validation_error"
        assert list(session.scalars(select(ApprovalRequest))) == []
    finally:
        session.close()
