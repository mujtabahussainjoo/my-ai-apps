"""Direct tool execution for the desktop UI.

The UI never gets a bypass: every call goes through the same registry, argument
validation, permission check and approval gate the agent uses. Side-effecting
tools return ``status: "approval_required"`` until the user approves them in the
UI, and approvals are bound to the exact arguments that were shown.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexapilot.api.deps import SessionDep
from nexapilot.core.container import Container
from nexapilot.core.errors import NotFoundError
from nexapilot.db.models import ApprovalRequest
from nexapilot.services import approvals
from nexapilot.tools.base import (
    Tool,
    ToolContext,
    ToolRegistry,
    execute_tool,
    parse_arguments,
)

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolRunRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str = Field(default="", max_length=64)


class ApprovalDecision(BaseModel):
    approved: bool = True
    note: str = Field(default="", max_length=2000)


def _registry(request: Request) -> ToolRegistry:
    registry: ToolRegistry = request.app.state.registry
    return registry


@router.get("")
def list_tools(
    registry: ToolRegistry = Depends(_registry),
) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.spec.name,
            "purpose": tool.spec.purpose,
            "permissions": sorted(tool.spec.permissions),
            "side_effects": tool.spec.side_effects,
            "requires_approval": tool.spec.requires_approval,
            "approval_action": tool.spec.approval_action,
            "risk": str(tool.spec.risk),
            "timeout_seconds": tool.spec.timeout_seconds,
        }
        for tool in registry.all()
    ]


def _matching_approval(
    session: Session, *, action: str, arguments: dict[str, Any]
) -> ApprovalRequest | None:
    stmt = (
        select(ApprovalRequest)
        .where(ApprovalRequest.action == action)
        .where(ApprovalRequest.status.in_(("pending", "approved")))
        .order_by(ApprovalRequest.created_at.desc())
    )
    for request in session.scalars(stmt):
        if request.payload.get("arguments") == arguments:
            return request
    return None


@router.post("/{tool_name}")
async def run_tool(
    tool_name: str,
    payload: ToolRunRequest,
    request: Request,
    session: Session = SessionDep,
    registry: ToolRegistry = Depends(_registry),
) -> dict[str, Any]:
    container: Container = request.app.state.container
    if not registry.has(tool_name):
        raise NotFoundError(f"Tool '{tool_name}' not found")
    tool: Tool = registry.get(tool_name)
    spec = tool.spec
    action = spec.approval_action or tool_name
    arguments = payload.arguments
    # Validate before asking for consent: never show an approval for arguments
    # the tool would reject.
    parse_arguments(spec, arguments)

    approval: ApprovalRequest | None = None
    if spec.requires_approval:
        approval = _matching_approval(session, action=action, arguments=arguments)
        if approval is None or approval.status != "approved":
            if approval is None:
                approval = approvals.create_request(
                    session,
                    action=action,
                    title=arguments.get("subject") or f"Run {tool_name}",
                    description=spec.purpose,
                    target=_target(arguments),
                    risk=str(spec.risk),
                    consequences="This action changes data outside NexaPilot.",
                    payload={"tool": tool_name, "arguments": arguments},
                )
                session.commit()
            return {
                "status": "approval_required",
                "approval": _approval_payload(approval),
            }

    ctx = ToolContext(
        container=container,
        session=session,
        conversation_id=payload.conversation_id,
        granted_permissions=spec.permissions,
    )
    result = await execute_tool(tool, arguments, ctx)
    if approval is not None:
        approvals.mark_executed(session, approval.id)
    session.commit()
    return {
        "status": "completed",
        "tool": tool_name,
        "output": result.model_dump(mode="json"),
        "approval_id": approval.id if approval is not None else "",
    }


@router.post("/{tool_name}/approvals/{approval_id}")
def decide_tool_approval(
    tool_name: str,
    approval_id: str,
    payload: ApprovalDecision,
    session: Session = SessionDep,
) -> dict[str, Any]:
    request = approvals.get_request(session, approval_id)
    if request.payload.get("tool") != tool_name:
        raise NotFoundError(f"Approval '{approval_id}' does not belong to tool '{tool_name}'")
    approvals.decide(session, approval_id, approved=payload.approved, note=payload.note)
    session.commit()
    return _approval_payload(request)


def _target(arguments: dict[str, Any]) -> str:
    for key in (
        "to",
        "recipient",
        "symbol",
        "path",
        "host",
        "destination",
        "calendar_id",
        "event_id",
        "rule_id",
        "channel_id",
    ):
        value = arguments.get(key)
        if isinstance(value, list) and value:
            return ", ".join(str(item) for item in value)[:300]
        if isinstance(value, str) and value:
            return value[:300]
    return ""


def _approval_payload(request: ApprovalRequest) -> dict[str, Any]:
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
        "created_at": request.created_at,
    }
