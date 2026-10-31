"""LangGraph assembly.

The graph is intentionally small and explicit:

    START -> classify -> agent_<workflow> -> finalize -> END

Routing is deterministic. Long-running or approval-blocked runs are persisted as
LangGraph checkpoints so they can be resumed.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from nexapilot.agents.llm_loop import AgentTurnResult, run_agent_turn
from nexapilot.agents.permissions import permissions_for_workflow, tools_for_workflow
from nexapilot.agents.prompts import system_prompt
from nexapilot.agents.state import ALL_WORKFLOWS, AgentState
from nexapilot.agents.supervisor import classify_request, validate_workflow
from nexapilot.core.container import Container
from nexapilot.core.errors import (
    ConfigurationError,
    NexaPilotError,
    RunCancelledError,
)
from nexapilot.core.logging import get_logger
from nexapilot.db.models import Message
from nexapilot.providers.base import Provider
from nexapilot.tools.base import ToolContext, ToolRegistry

log = get_logger(__name__)

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]

MAX_HISTORY_MESSAGES = 20


@dataclass
class RunContext:
    """Per-invocation dependencies. Kept out of the checkpointed state."""

    container: Container
    registry: ToolRegistry
    session: Any
    provider: Provider | None = None
    task_run_id: str = ""
    conversation_id: str = ""
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    approved_actions: dict[str, str] = field(default_factory=dict)
    emit: EmitFn | None = None
    granted_permissions: frozenset[str] = frozenset()


_run_context: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "nexapilot_run_context", default=None
)


def set_run_context(ctx: RunContext) -> contextvars.Token[RunContext | None]:
    return _run_context.set(ctx)


def reset_run_context(token: contextvars.Token[RunContext | None]) -> None:
    _run_context.reset(token)


def current_run_context() -> RunContext:
    ctx = _run_context.get()
    if ctx is None:
        raise RuntimeError("no run context is active")
    return ctx


def _load_history(session: Any, conversation_id: str) -> list[dict[str, Any]]:
    if not conversation_id:
        return []
    from sqlalchemy import select

    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(MAX_HISTORY_MESSAGES)
        )
    )
    rows.reverse()
    history: list[dict[str, Any]] = []
    for row in rows:
        history.append({"role": row.role, "content": row.content})
    return history


async def classify_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Route the request to exactly one workflow."""
    request = state.get("user_request", "")
    existing = state.get("workflow") or ""
    metadata = dict(state.get("metadata") or {})
    if existing and validate_workflow(existing) == existing:
        # An explicitly requested workflow always wins over the classifier.
        workflow = existing
        metadata["routing"] = {
            "workflow": existing,
            "confidence": 1.0,
            "reason": "requested explicitly",
            "signals": [],
        }
    else:
        decision = classify_request(request)
        workflow = decision.workflow
        metadata["routing"] = decision.to_dict()
    await _emit({"type": "routing", "workflow": workflow, "detail": metadata.get("routing")})
    return {"workflow": workflow, "metadata": metadata}


def _workflow_tools(ctx: RunContext, workflow: str) -> list[Any]:
    names = list(tools_for_workflow(workflow))
    permitted = {
        tool.spec.name
        for tool in ctx.registry.all()
        if tool.spec.permissions <= ctx.granted_permissions
    }
    selected = [name for name in names if name in permitted]
    return ctx.registry.definitions(selected)


def make_agent_node(workflow: str) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        ctx = current_run_context()
        metadata = dict(state.get("metadata") or {})
        pending_call = metadata.get("pending_tool_call")

        await _emit({"type": "agent_start", "workflow": workflow})

        if ctx.provider is None:
            return {
                "status": "error",
                "error": "No model provider is active. Open Settings and activate a provider.",
                "final_answer": (
                    "No model provider is active, so I cannot answer yet. "
                    "Open Settings, choose a provider, and press Save & Activate."
                ),
                "metadata": metadata,
            }

        history = _load_history(ctx.session, ctx.conversation_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(workflow)}]
        messages.extend(history)
        messages.append({"role": "user", "content": state.get("user_request", "")})

        tools = _workflow_tools(ctx, workflow)
        tool_ctx = ToolContext(
            container=ctx.container,
            session=ctx.session,
            task_run_id=ctx.task_run_id,
            conversation_id=ctx.conversation_id,
            granted_permissions=ctx.granted_permissions,
            cancel_event=ctx.cancel_event,
        )

        try:
            result: AgentTurnResult = await run_agent_turn(
                ctx.provider,
                messages=messages,
                tools=tools,
                registry=ctx.registry,
                ctx=tool_ctx,
                max_iterations=ctx.container.settings.max_tool_iterations,
                emit=_emit,
                pending_call=pending_call,
                approved_actions=ctx.approved_actions,
            )
        except RunCancelledError:
            return {
                "status": "cancelled",
                "final_answer": "",
                "tool_results": [],
                "citations": [],
                "metadata": metadata,
                "iteration": 0,
            }

        metadata.pop("pending_tool_call", None)

        if result.cancelled:
            return {
                "status": "cancelled",
                "final_answer": result.text,
                "tool_results": result.tool_calls_made,
                "citations": result.citations,
                "metadata": metadata,
                "iteration": result.iterations,
            }

        if result.pending_approval:
            metadata["pending_approval"] = result.pending_approval
            return {
                "status": "awaiting_approval",
                "final_answer": result.text
                or "I need your approval before I can continue with that action.",
                "tool_results": result.tool_calls_made,
                "citations": result.citations,
                "metadata": metadata,
                "iteration": result.iterations,
            }

        status = "completed" if not result.error else "partial"
        answer = result.text
        if result.error and not answer:
            answer = f"The run could not be completed: {result.error}"
        elif result.error:
            answer = f"{answer}\n\n_Note: {result.error}_"

        return {
            "status": status,
            "error": result.error,
            "final_answer": answer,
            "tool_results": result.tool_calls_made,
            "citations": result.citations,
            "messages": [message for message in messages if message.get("role") != "system"]
            + [{"role": "assistant", "content": answer}],
            "metadata": metadata,
            "iteration": result.iterations,
        }

    node.__name__ = f"agent_{workflow}"
    return node


async def finalize_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    await _emit({"type": "finalize"})
    return {"status": state.get("status", "completed")}


def route_after_classify(state: AgentState) -> str:
    workflow = validate_workflow(state.get("workflow", "general"))
    return f"agent_{workflow}"


def route_after_agent(state: AgentState) -> str:
    status = state.get("status", "completed")
    if status in ("awaiting_approval", "error"):
        return END
    return "finalize"


async def _emit(event: dict[str, Any]) -> None:
    ctx = _run_context.get()
    if ctx is None or ctx.emit is None:
        return
    try:
        await ctx.emit(event)
    except Exception:
        log.warning("agent.emit_failed", event_type=event.get("type"))


def build_graph(checkpointer: Any = None) -> Any:
    """Compile the NexaPilot graph."""
    builder = StateGraph(AgentState)
    builder.add_node("classify", classify_node)
    for workflow in ALL_WORKFLOWS:
        builder.add_node(f"agent_{workflow}", make_agent_node(workflow))
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify",
        route_after_classify,
        {f"agent_{workflow}": f"agent_{workflow}" for workflow in ALL_WORKFLOWS},
    )
    for workflow in ALL_WORKFLOWS:
        builder.add_conditional_edges(
            f"agent_{workflow}",
            route_after_agent,
            {"finalize": "finalize", END: END},
        )
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


async def resolve_active_provider(container: Container, session: Any) -> Provider:
    from nexapilot.services.provider_settings import get_active_provider

    return get_active_provider(session, container.secrets)


__all__ = [
    "ConfigurationError",
    "NexaPilotError",
    "RunContext",
    "build_graph",
    "current_run_context",
    "permissions_for_workflow",
    "reset_run_context",
    "resolve_active_provider",
    "set_run_context",
]
