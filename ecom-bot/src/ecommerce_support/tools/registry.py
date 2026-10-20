"""Typed tool registry with per-agent allowlists, validation, and audit (FR-027, SEC-010).

Tools are plain Python classes with a Pydantic argument model and :class:`ToolContext`. The
registry validates arguments, enforces per-agent allowlists and auth requirements, and emits
redacted audit events. It is framework-free (no LangChain/LangGraph) and unit-testable.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, ClassVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from ecommerce_support.core.exceptions import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from ecommerce_support.core.ids import new_id
from ecommerce_support.core.logging import get_logger
from ecommerce_support.core.metrics import COUNTER_TOOL_CALLS, get_metrics
from ecommerce_support.llm.types import ToolDefinition
from ecommerce_support.schemas.agents import ToolContext, ToolResult
from ecommerce_support.schemas.audit import AuditEventCreate
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools.audit import AuditHook, LoggingAuditHook

__all__ = ["Tool", "ToolRegistry", "create_tool_registry"]

_logger = get_logger("ecommerce_support.tools.registry")


class _NoArguments(BaseModel):
    """Default argument model for tools that take no inputs."""


class Tool[ArgsT: BaseModel](ABC):
    """A callable capability exposed to agents.

    Subclasses declare ``name``, ``arguments_model`` (a Pydantic model), and ``allowed_agents``
    (the only agents permitted to call it), then implement :meth:`run`.
    """

    name: ClassVar[str]
    description: ClassVar[str] = ""
    arguments_model: ClassVar[type[ArgsT]] = _NoArguments  # type: ignore[assignment]
    allowed_agents: ClassVar[frozenset[AgentName]] = frozenset()
    requires_auth: ClassVar[bool] = False
    audit: ClassVar[bool] = True
    timeout_seconds: ClassVar[float | None] = None

    @classmethod
    def parameters_schema(cls) -> dict[str, object]:
        """JSON-schema-style parameter object derived from the argument model."""
        return cls.arguments_model.model_json_schema()

    @abstractmethod
    async def run(self, arguments: ArgsT, context: ToolContext) -> dict[str, object]:
        """Execute the tool and return a JSON-serializable output payload."""
        raise NotImplementedError

    def summarize(self, result: dict[str, object]) -> str:
        """Return a short, redacted summary for audit/logging (default: empty)."""
        return ""


class ToolRegistry:
    """Holds registered tools and mediates every invocation."""

    def __init__(
        self,
        tools: Iterable[Tool[Any]] = (),
        *,
        audit_hook: AuditHook | None = None,
    ) -> None:
        self._tools: dict[str, Tool[Any]] = {}
        self._audit_hook: AuditHook = audit_hook or LoggingAuditHook()
        for tool in tools:
            self.register(tool)

    # -- registration ------------------------------------------------------

    def register(self, tool: Tool[Any]) -> None:
        """Register ``tool`` (fails loudly on a missing name, duplicate, or empty allowlist)."""
        name = tool.name
        if not name:
            msg = "Tool name must not be empty."
            raise ValueError(msg)
        if tool.name in self._tools:
            raise ConflictError(
                "A tool with this name is already registered.", details={"tool": tool.name}
            )
        if not tool.allowed_agents:
            raise ValueError(f"Tool {name!r} must allow at least one agent.")
        self._tools[tool.name] = tool

    # -- introspection -----------------------------------------------------

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        """Registered tool names, sorted."""
        return sorted(self._tools)

    def get(self, name: str) -> Tool[Any]:
        """Return a registered tool or raise :class:`NotFoundError`."""
        tool = self._tools.get(name)
        if tool is None:
            raise NotFoundError("Unknown tool.", details={"tool": name})
        return tool

    def list_tools(self, agent: AgentName | None = None) -> list[Tool[Any]]:
        """All tools, optionally filtered to those ``agent`` is allowed to call."""
        tools: Iterable[Tool[Any]] = self._tools.values()
        if agent is not None:
            tools = [tool for tool in tools if agent in tool.allowed_agents]
        return sorted(tools, key=lambda tool: tool.name)

    def definitions(self, agent: AgentName) -> list[ToolDefinition]:
        """Provider-neutral tool definitions (for the LLM layer) available to ``agent``."""
        return [
            ToolDefinition(
                name=tool.name,
                description=tool.description,
                parameters=dict(tool.parameters_schema()),
            )
            for tool in self.list_tools(agent)
        ]

    # -- invocation --------------------------------------------------------

    async def invoke(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
        *,
        context: ToolContext,
        call_id: str | None = None,
    ) -> ToolResult:
        """Validate, authorize, and run a tool call; never leaks arguments to the audit hook.

        Boundary violations raise (:class:`NotFoundError` / :class:`AuthorizationError` /
        :class:`AuthenticationError` / :class:`ValidationError`). Failures *inside* a tool are
        returned as an error :class:`ToolResult` so the agent can explain them to the customer.
        """
        resolved_id = call_id or new_id("call")
        tool = self.get(name)

        if context.agent not in tool.allowed_agents:
            get_metrics().increment(COUNTER_TOOL_CALLS, tool=tool.name, status="denied")
            await self._audit("tool.denied", tool, context, reason="agent_not_allowed")
            raise AuthorizationError(
                f"The {context.agent.value} agent may not call {tool.name}.",
                details={"tool": tool.name, "agent": context.agent.value},
            )
        if tool.requires_auth and not context.user_id:
            get_metrics().increment(COUNTER_TOOL_CALLS, tool=tool.name, status="unauthenticated")
            await self._audit("tool.unauthenticated", tool, context)
            raise AuthenticationError(
                "This action requires a signed-in customer.",
                details={"tool": tool.name},
            )

        try:
            validated = tool.arguments_model.model_validate(arguments or {})
        except PydanticValidationError as exc:
            get_metrics().increment(COUNTER_TOOL_CALLS, tool=tool.name, status="invalid")
            await self._audit("tool.invalid_arguments", tool, context)
            raise ValidationError(
                "Invalid tool arguments.",
                details={"tool": tool.name, "errors": exc.error_count()},
            ) from exc

        started = time.perf_counter()
        try:
            output = await tool.run(validated, context)
        except Exception as exc:
            get_metrics().increment(COUNTER_TOOL_CALLS, tool=tool.name, status="error")
            await self._audit("tool.failed", tool, context, reason=type(exc).__name__)
            return ToolResult(
                call_id=resolved_id,
                tool_name=tool.name,
                status=ToolCallStatus.ERROR,
                error=_safe_error(exc),
                duration_ms=_elapsed_ms(started),
            )

        get_metrics().increment(COUNTER_TOOL_CALLS, tool=tool.name, status="ok")
        await self._audit("tool.invoked", tool, context)
        return ToolResult(
            call_id=resolved_id,
            tool_name=tool.name,
            status=ToolCallStatus.OK,
            output=output,
            summary=tool.summarize(output),
            duration_ms=_elapsed_ms(started),
        )

    # -- internals ---------------------------------------------------------

    async def _audit(
        self,
        event_type: str,
        tool: Tool[Any],
        context: ToolContext,
        **detail: object,
    ) -> None:
        if not tool.audit:
            return
        event = AuditEventCreate(
            event_type=event_type,
            actor_id=context.user_id,
            resource_type="tool",
            resource_id=tool.name,
            conversation_id=context.conversation_id,
            detail={"agent": context.agent.value, "tenant_id": context.tenant_id, **detail},
        )
        try:
            await self._audit_hook.record(event)
        except Exception:  # auditing must never break a request
            _logger.warning("tool.audit_failed", event_type=event_type, tool=tool.name)


def create_tool_registry(
    tools: Iterable[Tool[Any]] = (),
    *,
    audit_hook: AuditHook | None = None,
) -> ToolRegistry:
    """Build a registry (optionally pre-populated) with the given audit hook."""
    return ToolRegistry(tools, audit_hook=audit_hook)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, AppError):
        return exc.message
    return "The tool failed to complete the request."
