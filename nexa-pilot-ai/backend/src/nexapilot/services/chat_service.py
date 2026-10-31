"""Chat service: the end-to-end conversational workflow.

This is where the pieces meet: the active provider, the LangGraph supervisor,
the tool registry, approvals, persistence and streaming.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from nexapilot.agents.graph import RunContext, reset_run_context, set_run_context
from nexapilot.agents.permissions import (
    CALENDAR_READ,
    CALENDAR_WRITE,
    EMAIL_MODIFY,
    EMAIL_READ,
    EMAIL_SEND,
    FINANCE_READ,
    FINANCE_TRADE,
    FS_READ,
    FS_WRITE,
    SHELL_EXEC,
    TRAVEL_SEARCH,
    WEB_SEARCH,
)
from nexapilot.core.container import Container
from nexapilot.core.errors import ConfigurationError
from nexapilot.core.logging import get_logger
from nexapilot.db.models import ConnectedAccount, Conversation, Message, TaskRun
from nexapilot.providers.base import Provider
from nexapilot.tools.base import ToolRegistry

log = get_logger(__name__)


@dataclass
class ChatInput:
    message: str
    conversation_id: str = ""
    workflow: str = ""
    timezone: str = "UTC"


@dataclass
class ChatOutcome:
    task_run_id: str = ""
    conversation_id: str = ""
    answer: str = ""
    status: str = "completed"
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    error: str = ""


class ChatService:
    def __init__(self, container: Container, registry: ToolRegistry, graph: Any) -> None:
        self.container = container
        self.registry = registry
        self.graph = graph

    # -- permissions ---------------------------------------------------------

    def granted_permissions(self, session: Any) -> frozenset[str]:
        """Permissions derived from configuration and connected accounts."""
        settings = self.container.settings
        granted: set[str] = {FINANCE_READ, FINANCE_TRADE}

        if settings.coding_workspace_root:
            granted.update({FS_READ, FS_WRITE, SHELL_EXEC})

        accounts = list(
            session.scalars(select(ConnectedAccount).where(ConnectedAccount.status == "connected"))
        )
        for account in accounts:
            if account.provider in ("gmail", "imap"):
                granted.update({EMAIL_READ, EMAIL_MODIFY, EMAIL_SEND})
            if account.provider in ("google_calendar", "gmail"):
                granted.update({CALENDAR_READ, CALENDAR_WRITE})
        if settings.travel_provider:
            granted.add(TRAVEL_SEARCH)
        if settings.web_search_provider:
            granted.add(WEB_SEARCH)
        return frozenset(granted)

    # -- conversations -------------------------------------------------------

    def ensure_conversation(self, session: Any, conversation_id: str = "") -> Conversation:
        if conversation_id:
            conversation: Conversation | None = session.get(Conversation, conversation_id)
            if conversation is not None:
                return conversation
        conversation = Conversation(title="New conversation")
        session.add(conversation)
        session.flush()
        return conversation

    def list_conversations(self, session: Any, limit: int = 50) -> list[dict[str, Any]]:
        rows = list(
            session.scalars(
                select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
            )
        )
        return [
            {
                "id": row.id,
                "title": row.title,
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]

    def list_messages(self, session: Any, conversation_id: str) -> list[dict[str, Any]]:
        rows = list(
            session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.asc())
            )
        )
        return [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "provider": row.provider,
                "model": row.model,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    # -- execution -----------------------------------------------------------

    async def run_chat(
        self,
        session: Any,
        payload: ChatInput,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one chat turn, yielding progress events."""
        cancel_event = cancel_event or asyncio.Event()
        conversation = self.ensure_conversation(session, payload.conversation_id)

        session.add(
            Message(
                conversation_id=conversation.id,
                role="user",
                content=payload.message,
            )
        )

        task_run = TaskRun(
            conversation_id=conversation.id,
            workflow=payload.workflow or "general",
            status="running",
            request={"message": payload.message[:2000]},
        )
        session.add(task_run)
        session.flush()

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        provider: Provider | None = None
        try:
            provider = self._resolve_provider(session)
        except ConfigurationError as exc:
            # Keep the user's message and the failed run, but do not lose the trace.
            task_run.status = "failed"
            task_run.error = exc.message
            task_run.completed_at = datetime.now(UTC)
            session.commit()
            yield {
                "type": "error",
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
            return

        task_run.provider = provider.provider_id
        task_run.model = provider.model
        conversation.provider = provider.provider_id
        conversation.model = provider.model
        session.flush()

        run_context = RunContext(
            container=self.container,
            registry=self.registry,
            provider=provider,
            session=session,
            task_run_id=task_run.id,
            conversation_id=conversation.id,
            cancel_event=cancel_event,
            approved_actions={},
            emit=emit,
            granted_permissions=self.granted_permissions(session),
        )

        state: dict[str, Any] = {
            "messages": [],
            "workflow": payload.workflow,
            "user_request": payload.message,
            "conversation_id": conversation.id,
            "task_run_id": task_run.id,
            "provider_id": provider.provider_id,
            "model": provider.model,
            "thread_id": task_run.id,
            "iteration": 0,
            "citations": [],
            "tool_results": [],
            "approvals": [],
            "final_answer": "",
            "status": "running",
            "error": "",
            "metadata": {"timezone": payload.timezone},
        }

        runner = asyncio.create_task(self._invoke_graph(run_context, state, task_run.id))
        waiter = asyncio.create_task(queue.get())

        try:
            while True:
                done, _ = await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if waiter in done:
                    event = waiter.result()
                    waiter = asyncio.create_task(queue.get())
                    if event is None:
                        break
                    yield event
                if runner in done:
                    break
            # drain remaining events
            while not queue.empty():
                event = queue.get_nowait()
                if event is None:
                    continue
                yield event
            result = runner.result()
        except asyncio.CancelledError:
            runner.cancel()
            task_run.status = "cancelled"
            task_run.completed_at = datetime.now(UTC)
            session.commit()
            yield {"type": "cancelled", "message": "The run was cancelled."}
            raise
        finally:
            for task in (runner, waiter):
                if not task.done():
                    task.cancel()

        status = result.get("status", "completed")
        if status == "cancelled":
            task_run.status = "cancelled"
            task_run.completed_at = datetime.now(UTC)
            session.commit()
            yield {"type": "cancelled", "message": "The run was cancelled."}
            return
        answer = result.get("final_answer", "")
        task_run.status = status
        task_run.result = {
            "answer": answer,
            "citations": result.get("citations", []),
        }
        task_run.error = result.get("error", "")
        task_run.steps = int(result.get("iteration") or 0)
        task_run.completed_at = datetime.now(UTC)

        if answer:
            session.add(
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=answer,
                    provider=provider.provider_id,
                    model=provider.model,
                )
            )
        if not conversation.title or conversation.title == "New conversation":
            conversation.title = (
                payload.message.strip().splitlines()[0][:120]
                if payload.message
                else "New conversation"
            )
        session.commit()

        yield {
            "type": "done",
            "task_run_id": task_run.id,
            "conversation_id": conversation.id,
            "status": status,
            "answer": answer,
            "citations": result.get("citations", []),
            "tool_results": result.get("tool_results", []),
            "provider": provider.provider_id,
            "model": provider.model,
            "error": result.get("error", ""),
        }

    async def _invoke_graph(
        self, run_context: RunContext, state: dict[str, Any], thread_id: str
    ) -> dict[str, Any]:
        token = set_run_context(run_context)
        try:
            config = {"configurable": {"thread_id": thread_id}}
            outcome: dict[str, Any] = await self.graph.ainvoke(state, config=config)
            return outcome
        finally:
            reset_run_context(token)

    def _resolve_provider(self, session: Any) -> Provider:
        from nexapilot.services.provider_settings import get_active_provider

        return get_active_provider(session, self.container.secrets)

    # -- approvals -----------------------------------------------------------

    async def resume_approved_action(
        self,
        session: Any,
        *,
        approval_id: str,
        conversation_id: str = "",
    ) -> AsyncIterator[dict[str, Any]]:
        """Resume a run that was blocked on an approval."""
        from nexapilot.services import approvals as approval_service

        approval = approval_service.get_request(session, approval_id)
        if approval.status != "approved":
            yield {
                "type": "error",
                "code": "approval_required",
                "message": (
                    f"Approval '{approval_id}' is not granted (status: {approval.status})."
                ),
            }
            return

        payload = approval.payload or {}
        tool_name = str(payload.get("tool") or "")
        arguments = payload.get("arguments") or {}
        action = approval.action

        task_run = session.get(TaskRun, approval.task_run_id) if approval.task_run_id else None
        existing_conversation_id = conversation_id or (task_run.conversation_id if task_run else "")
        conversation = self.ensure_conversation(session, existing_conversation_id)
        if task_run is None:
            task_run = TaskRun(
                conversation_id=conversation.id,
                workflow="general",
                status="running",
                request={"resumed_from_approval": approval_id},
            )
            session.add(task_run)
            session.flush()

        provider = self._resolve_provider(session)

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        run_context = RunContext(
            container=self.container,
            registry=self.registry,
            provider=provider,
            session=session,
            task_run_id=task_run.id,
            conversation_id=conversation.id,
            cancel_event=asyncio.Event(),
            approved_actions={action: approval_id},
            emit=emit,
            granted_permissions=self.granted_permissions(session),
        )

        state: dict[str, Any] = {
            "messages": [],
            "workflow": task_run.workflow,
            "user_request": f"Continue with the approved action '{action}'.",
            "conversation_id": conversation.id,
            "task_run_id": task_run.id,
            "provider_id": provider.provider_id,
            "model": provider.model,
            "thread_id": task_run.id,
            "iteration": 0,
            "citations": [],
            "tool_results": [],
            "approvals": [],
            "final_answer": "",
            "status": "running",
            "error": "",
            "metadata": {
                "pending_tool_call": {
                    "id": f"approval-{approval_id}",
                    "name": tool_name,
                    "arguments": arguments,
                },
                "approval_id": approval_id,
            },
        }

        runner = asyncio.create_task(self._invoke_graph(run_context, state, task_run.id))
        waiter = asyncio.create_task(queue.get())
        try:
            while True:
                done, _ = await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
                if waiter in done:
                    event = waiter.result()
                    waiter = asyncio.create_task(queue.get())
                    if event is None:
                        break
                    yield event
                if runner in done:
                    break
            while not queue.empty():
                event = queue.get_nowait()
                if event is None:
                    continue
                yield event
            result = runner.result()
        finally:
            for task in (runner, waiter):
                if not task.done():
                    task.cancel()

        approval_service.mark_executed(session, approval_id)
        answer = result.get("final_answer", "")
        task_run.status = result.get("status", "completed")
        task_run.result = {"answer": answer}
        task_run.completed_at = datetime.now(UTC)
        if answer:
            session.add(
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=answer,
                    provider=provider.provider_id,
                    model=provider.model,
                )
            )
        session.commit()
        yield {
            "type": "done",
            "task_run_id": task_run.id,
            "conversation_id": conversation.id,
            "status": task_run.status,
            "answer": answer,
            "citations": result.get("citations", []),
            "tool_results": result.get("tool_results", []),
        }
