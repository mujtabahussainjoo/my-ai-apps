"""Tool contracts.

Every tool declares what it does, what it needs, what it changes, and how it is
audited. Tool arguments are validated with Pydantic before execution and tool
output is treated as untrusted data by the agent layer.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from nexapilot.core.container import Container
from nexapilot.core.errors import (
    NexaPilotError,
    PermissionDeniedError,
    RunCancelledError,
    ToolExecutionError,
    ToolTimeoutError,
)
from nexapilot.core.errors import (
    ValidationError as NexaValidationError,
)
from nexapilot.core.logging import get_logger
from nexapilot.providers.base import ToolDefinition

log = get_logger(__name__)


class ToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ToolPermission:
    """A permission string such as ``email:send`` or ``fs:write``."""

    name: str
    description: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


@dataclass(frozen=True)
class ToolSpec:
    name: str
    purpose: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permissions: frozenset[str] = frozenset()
    side_effects: bool = False
    timeout_seconds: float = 60.0
    max_retries: int = 0
    idempotent: bool = True
    audit: bool = True
    requires_approval: bool = False
    approval_action: str = ""
    risk: ToolRisk = ToolRisk.LOW
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_definition(self) -> ToolDefinition:
        schema = self.input_model.model_json_schema()
        return ToolDefinition(
            name=self.name,
            description=self.purpose,
            parameters=schema,
        )


@dataclass
class ToolContext:
    """Everything a tool is allowed to touch."""

    container: Container
    session: Session
    task_run_id: str = ""
    conversation_id: str = ""
    granted_permissions: frozenset[str] = frozenset()
    cancel_event: asyncio.Event | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise RunCancelledError("Operation cancelled by the user")

    def has_permission(self, permission: str) -> bool:
        return permission in self.granted_permissions

    def require_permissions(self, permissions: frozenset[str]) -> None:
        missing = sorted(permissions - self.granted_permissions)
        if missing:
            raise PermissionDeniedError(
                f"Missing required permission(s): {', '.join(missing)}",
                details={"missing": missing},
            )


class Tool(abc.ABC):
    """Base class for all tools."""

    spec: ToolSpec

    @abc.abstractmethod
    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel: ...


class SimpleTool(Tool):
    """Convenience base: define the spec and an async handler."""

    spec: ToolSpec

    def __init__(self, spec: ToolSpec, handler: Any) -> None:
        self.spec = spec
        self._handler = handler

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        output: BaseModel = await self._handler(args, ctx)
        return output


class ToolRegistry:
    """Holds the tools available to agents."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"tool '{name}' is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise NexaValidationError(f"Unknown tool '{name}'")
        return tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def definitions(self, names: list[str] | None = None) -> list[ToolDefinition]:
        selected = self.all() if names is None else [self.get(name) for name in names]
        return [tool.spec.to_definition() for tool in selected]

    def permitted(self, granted: frozenset[str]) -> list[Tool]:
        return [tool for tool in self.all() if tool.spec.permissions <= granted]


def parse_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> BaseModel:
    """Validate raw model-produced arguments against the tool's input schema."""
    if not isinstance(arguments, dict):
        raise NexaValidationError(f"Tool '{spec.name}' expects a JSON object of arguments")
    try:
        return spec.input_model.model_validate(arguments)
    except ValidationError as exc:
        raise NexaValidationError(
            f"Invalid arguments for tool '{spec.name}'",
            details={"tool": spec.name, "errors": _summarize(exc)},
        ) from exc


def _summarize(exc: ValidationError, limit: int = 5) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for error in exc.errors()[:limit]:
        summary.append(
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "message": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
        )
    return summary


async def execute_tool(
    tool: Tool,
    arguments: dict[str, Any],
    ctx: ToolContext,
) -> BaseModel:
    """Validate, authorise and run a tool with timeout and bounded retries."""
    spec = tool.spec
    ctx.require_permissions(spec.permissions)
    args = parse_arguments(spec, arguments)
    ctx.check_cancelled()

    attempts = spec.max_retries + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            result = await asyncio.wait_for(tool.run(args, ctx), timeout=spec.timeout_seconds)
        except TimeoutError:
            last_error = ToolTimeoutError(
                f"Tool '{spec.name}' timed out after {spec.timeout_seconds:.0f}s",
                details={"tool": spec.name},
            )
            break
        except RunCancelledError:
            _record_audit(ctx, spec, status="cancelled")
            raise
        except NexaPilotError:
            _record_audit(ctx, spec, status="error")
            raise
        except Exception as exc:
            last_error = ToolExecutionError(
                f"Tool '{spec.name}' failed: {type(exc).__name__}",
                details={"tool": spec.name},
            )
            log.warning(
                "tool.failed", tool=spec.name, error=type(exc).__name__, attempt=attempt + 1
            )
            if attempt + 1 >= attempts:
                break
            continue
        _record_audit(ctx, spec, status="ok")
        return result
    _record_audit(ctx, spec, status="error")
    assert last_error is not None
    raise last_error


def _record_audit(ctx: ToolContext, spec: ToolSpec, *, status: str) -> None:
    """Record tool activity without arguments so secrets and content never leak."""
    if not spec.audit or ctx.session is None:
        return
    try:
        from nexapilot.services.audit import record

        record(
            ctx.session,
            action=f"tool.{spec.name}",
            target=f"conversation:{ctx.conversation_id}" if ctx.conversation_id else "",
            status=status,
            details={
                "permissions": sorted(spec.permissions),
                "side_effects": spec.side_effects,
                "approval_action": spec.approval_action,
            },
        )
    except Exception:
        log.warning("tool.audit_failed", tool=spec.name)
