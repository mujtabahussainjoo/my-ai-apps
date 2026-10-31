"""The agent tool loop.

One turn of an agent: send the conversation to the active provider, execute any
tool calls the model requested, feed the results back, repeat — with a hard
iteration bound. Approvals are enforced here and in the tool layer, never by
prompt wording.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from nexapilot.core.errors import NexaPilotError, RunCancelledError
from nexapilot.core.logging import get_logger
from nexapilot.providers.base import ChatMessage, ChatRequest, Provider, ToolCall, ToolDefinition
from nexapilot.tools.base import ToolContext, ToolRegistry, execute_tool, parse_arguments

log = get_logger(__name__)

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class AgentTurnResult:
    text: str = ""
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    pending_approval: dict[str, Any] | None = None
    error: str = ""
    iterations: int = 0
    cancelled: bool = False
    provider: str = ""
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


def _message_to_dict(message: ChatMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.name:
        payload["name"] = message.name
    if message.tool_calls:
        payload["tool_calls"] = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ]
    return payload


def _dict_to_message(payload: dict[str, Any]) -> ChatMessage:
    calls = [
        ToolCall(
            id=call.get("id", ""), name=call.get("name", ""), arguments=call.get("arguments") or {}
        )
        for call in payload.get("tool_calls") or []
    ]
    return ChatMessage(
        role=payload.get("role", "user"),
        content=payload.get("content", "") or "",
        name=payload.get("name"),
        tool_call_id=payload.get("tool_call_id"),
        tool_calls=calls,
    )


async def _noop_emit(event: dict[str, Any]) -> None:
    return None


async def run_agent_turn(
    provider: Provider,
    *,
    messages: list[dict[str, Any]],
    tools: list[ToolDefinition],
    registry: ToolRegistry,
    ctx: ToolContext,
    max_iterations: int = 6,
    temperature: float | None = None,
    emit: EmitFn | None = None,
    pending_call: dict[str, Any] | None = None,
    approved_actions: dict[str, str] | None = None,
) -> AgentTurnResult:
    """Run one agent turn, executing tool calls until the model stops."""
    emit = emit or _noop_emit
    approved_actions = approved_actions or {}
    conversation: list[dict[str, Any]] = [dict(message) for message in messages]
    result = AgentTurnResult(provider=provider.provider_id, model=provider.model)

    call_to_execute: dict[str, Any] | None = pending_call
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        result.iterations = iteration
        ctx.check_cancelled()

        if call_to_execute is not None:
            call = call_to_execute
            call_to_execute = None
            executed = await _execute_tool_call(
                call,
                registry=registry,
                ctx=ctx,
                approved_actions=approved_actions,
                result=result,
                emit=emit,
            )
            if executed is None:
                return result
            # Providers require the tool result to follow the assistant tool-call
            # message, so replay it before the result.
            conversation.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call.get("id", ""),
                            "name": call.get("name", ""),
                            "arguments": call.get("arguments") or {},
                        }
                    ],
                }
            )
            conversation.append(executed)
            continue

        request = ChatRequest(
            model=provider.model,
            messages=[_dict_to_message(message) for message in conversation],
            tools=tools,
            temperature=temperature,
        )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        try:
            async for event in provider.stream(request):
                ctx.check_cancelled()
                if event.type == "text" and event.text:
                    text_parts.append(event.text)
                    await emit({"type": "token", "text": event.text})
                elif event.type == "tool_call" and event.tool_call is not None:
                    tool_calls.append(event.tool_call)
                elif event.type == "usage" and event.usage is not None:
                    result.usage = {
                        "input_tokens": result.usage.get("input_tokens", 0)
                        + (event.usage.input_tokens or 0),
                        "output_tokens": result.usage.get("output_tokens", 0)
                        + (event.usage.output_tokens or 0),
                    }
                elif event.type == "error" and event.error:
                    result.error = str(event.error.get("message") or "provider stream error")
        except RunCancelledError:
            result.cancelled = True
            result.text = "".join(text_parts)
            return result
        except NexaPilotError as exc:
            result.error = exc.message
            await emit({"type": "error", "message": exc.message, "code": exc.code})
            if not text_parts:
                return result
            break

        assistant_text = "".join(text_parts)
        assistant_message: dict[str, Any] = {"role": "assistant", "content": assistant_text}
        if tool_calls:
            assistant_message["tool_calls"] = [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in tool_calls
            ]
        conversation.append(assistant_message)
        if assistant_text:
            result.text = assistant_text

        if not tool_calls:
            break

        for tool_call in tool_calls:
            tool_message = await _execute_tool_call(
                {
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                },
                registry=registry,
                ctx=ctx,
                approved_actions=approved_actions,
                result=result,
                emit=emit,
            )
            if tool_message is None:
                return result
            conversation.append(tool_message)

    if iteration >= max_iterations and not result.error:
        result.error = f"Stopped after {max_iterations} tool iterations to keep the run bounded."
    if not result.text and conversation:
        last = conversation[-1]
        if last.get("role") == "assistant":
            result.text = str(last.get("content") or "")
    return result


async def _execute_tool_call(
    call: dict[str, Any],
    *,
    registry: ToolRegistry,
    ctx: ToolContext,
    approved_actions: dict[str, str],
    result: AgentTurnResult,
    emit: EmitFn,
) -> dict[str, Any] | None:
    """Execute one tool call. Returns the tool message, or ``None`` to stop."""
    name = str(call.get("name") or "")
    arguments = call.get("arguments") or {}
    call_id = str(call.get("id") or "")

    if not registry.has(name):
        message = f"Unknown tool '{name}'"
        await emit({"type": "tool_error", "tool": name, "message": message})
        return {"role": "tool", "name": name, "tool_call_id": call_id, "content": message}

    tool = registry.get(name)
    spec = tool.spec

    try:
        parse_arguments(spec, arguments)
    except NexaPilotError as exc:
        await emit({"type": "tool_error", "tool": name, "message": exc.message})
        result.tool_calls_made.append(
            {"tool": name, "status": "error", "error": exc.message, "code": exc.code}
        )
        return {
            "role": "tool",
            "name": name,
            "tool_call_id": call_id,
            "content": f"ERROR: {exc.message}",
        }

    if spec.requires_approval:
        granted = await _check_approval(spec, call, ctx, approved_actions, result, emit)
        if granted is None:
            return None

    await emit({"type": "tool_start", "tool": name, "arguments": _redact_arguments(arguments)})
    started = time.perf_counter()
    try:
        output = await execute_tool(tool, arguments, ctx)
    except NexaPilotError as exc:
        await emit({"type": "tool_error", "tool": name, "message": exc.message})
        result.tool_calls_made.append(
            {"tool": name, "status": "error", "error": exc.message, "code": exc.code}
        )
        return {
            "role": "tool",
            "name": name,
            "tool_call_id": call_id,
            "content": f"ERROR: {exc.message}",
        }

    payload = output.model_dump()
    result.tool_calls_made.append(
        {
            "tool": name,
            "status": "ok",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "output": payload,
        }
    )
    citations = payload.get("results") or payload.get("citations")
    if isinstance(citations, list):
        for item in citations:
            if isinstance(item, dict) and item.get("url"):
                result.citations.append(item)
    await emit({"type": "tool_end", "tool": name, "status": "ok"})
    return {
        "role": "tool",
        "name": name,
        "tool_call_id": call_id,
        "content": _render_tool_output(payload),
    }


async def _check_approval(
    spec: Any,
    call: dict[str, Any],
    ctx: ToolContext,
    approved_actions: dict[str, str],
    result: AgentTurnResult,
    emit: EmitFn,
) -> str | None:
    """Ensure an approval exists for a side-effecting tool.

    Returns ``"approved"`` when the action may proceed, ``None`` when the run must
    stop and wait for the user.
    """
    from nexapilot.services import approvals as approval_service

    action = spec.approval_action or spec.name
    approval_id = approved_actions.get(action)
    if approval_id:
        request = approval_service.get_request(ctx.session, approval_id)
        if request.status in ("approved", "executed") and request.action == action:
            return "approved"
        result.pending_approval = {
            "approval_id": request.id,
            "action": request.action,
            "status": request.status,
            "title": request.title,
        }
        await emit(
            {
                "type": "approval_required",
                "approval_id": request.id,
                "action": request.action,
                "status": request.status,
                "approval": _approval_event(request),
            }
        )
        return None

    request = approval_service.create_request(
        ctx.session,
        action=action,
        title=spec.purpose,
        description=spec.purpose,
        target=str(call.get("arguments", {}).get("target", ""))[:300],
        risk=str(spec.risk),
        payload={
            "tool": spec.name,
            "arguments": _redact_arguments(call.get("arguments") or {}),
            "task_run_id": ctx.task_run_id,
        },
        task_run_id=ctx.task_run_id,
    )
    ctx.session.commit()
    result.pending_approval = {
        "approval_id": request.id,
        "action": request.action,
        "status": request.status,
        "title": request.title,
        "description": request.description,
        "target": request.target,
        "risk": request.risk,
        "payload": request.payload,
    }
    await emit(
        {
            "type": "approval_required",
            "approval_id": request.id,
            "action": request.action,
            "status": request.status,
            "title": request.title,
            "description": request.description,
            "target": request.target,
            "risk": request.risk,
            "payload": request.payload,
            "approval": _approval_event(request),
        }
    )
    return None


def _approval_event(request: Any) -> dict[str, Any]:
    return {
        "id": request.id,
        "action": request.action,
        "title": request.title,
        "description": request.description,
        "target": request.target,
        "risk": request.risk,
        "cost": request.cost,
        "consequences": request.consequences,
        "status": request.status,
        "payload": request.payload,
        "created_at": request.created_at.isoformat() if request.created_at else None,
    }


def _redact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Remove obviously sensitive fields before logging or displaying arguments."""
    sensitive = ("password", "token", "secret", "api_key", "card", "cvv", "pin")
    redacted: dict[str, Any] = {}
    for key, value in arguments.items():
        if any(marker in key.lower() for marker in sensitive):
            redacted[key] = "<redacted>"
        elif isinstance(value, str) and len(value) > 2000:
            redacted[key] = value[:2000] + "…"
        else:
            redacted[key] = value
    return redacted


def _render_tool_output(payload: dict[str, Any]) -> str:
    import json

    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > 20_000:
        return text[:20_000] + "… (truncated)"
    return text
