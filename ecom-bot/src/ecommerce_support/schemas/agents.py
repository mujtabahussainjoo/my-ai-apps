"""Agent-layer contracts: routing decisions, graph state, tool calls, worker I/O.

These models are framework-free (no LangGraph import) so workers and tools can be tested
without a graph runtime. The LangGraph state is built from :class:`AgentState`.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.enums import (
    AgentName,
    Intent,
    ResolutionAction,
    ResolutionOutcome,
    TicketStatus,
    ToolCallStatus,
)


class SourceCitation(Schema):
    """A retrieved evidence pointer surfaced to the customer (FR-033)."""

    document_id: str
    chunk_id: str
    document_title: str | None = None
    section_title: str | None = None
    version: int | None = Field(default=None, ge=1)
    score: float = Field(ge=0.0)


class ToolCallRequest(Schema):
    """A validated request to invoke a registered tool."""

    tool_name: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolContext(Schema):
    """Caller context a tool invocation runs under (authorization + audit; FR-027)."""

    agent: AgentName
    user_id: str | None = None
    conversation_id: str | None = None
    tenant_id: str = "default"
    request_id: str | None = None


class ToolExecution(Schema):
    """Audit record of a single tool invocation (redacted summary only)."""

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: ToolCallStatus
    summary: str = ""
    duration_ms: float | None = Field(default=None, ge=0.0)


class ToolResult(Schema):
    """Outcome of a registry-mediated tool call (arguments already validated)."""

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: ToolCallStatus = ToolCallStatus.OK
    output: dict[str, Any] | None = None
    error: str | None = None
    summary: str = ""
    duration_ms: float | None = Field(default=None, ge=0.0)

    def to_execution(self) -> ToolExecution:
        """Project this result into the redacted audit record fed to the LLM layer."""
        return ToolExecution(
            call_id=self.call_id,
            tool_name=self.tool_name,
            status=self.status,
            summary=self.summary,
            duration_ms=self.duration_ms,
        )


class RoutingDecision(Schema):
    """Result of intent classification and agent selection (FR-015-FR-018)."""

    intent: Intent
    agent: AgentName
    requires_auth: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = ""


class ResolutionDecision(Schema):
    """The Resolution Agent's verdict after an answer (FR-024/FR-048).

    ``evidence_sufficient`` records whether the answer can stand on its own; ``retry_agent`` is the
    bounded alternative to try before escalating. Answer generation is never treated as proof of
    resolution — an answer only advances the flow to "ask the customer".
    """

    action: ResolutionAction
    reason: str = ""
    evidence_sufficient: bool = False
    retry_agent: AgentName | None = None
    outcome: ResolutionOutcome | None = None


class AgentState(Schema):
    """Typed workflow state tracked by the graph (FR-018).

    Carries the current turn's input, the routing decision, bounded-execution counters, retrieved
    evidence, and the assembled answer. No free-form fields: every channel has a typed contract.
    """

    conversation_id: str = Field(min_length=1)
    user_id: str | None = None
    tenant_id: str = "default"
    request_id: str | None = None
    message: str = ""
    intent: Intent | None = None
    selected_agent: AgentName | None = None
    requires_auth: bool = False
    router_reason: str = ""
    retry_count: int = Field(default=0, ge=0)
    iterations: int = Field(default=0, ge=0)
    hop_count: int = Field(default=0, ge=0)
    resolution_state: ResolutionOutcome | None = None
    resolution_action: ResolutionAction | None = None
    escalation_requested: bool = False
    ticket_status: TicketStatus | None = None
    evidence: list[SourceCitation] = Field(default_factory=list)
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    answer: str | None = None
    needs_clarification: bool = False
    abstained: bool = False
    attempts: list[str] = Field(default_factory=list)
    error: str | None = None

    def to_response(self) -> AgentResponse:
        """Project the state's answer fields into a typed worker/agent response."""
        return AgentResponse(
            agent=self.selected_agent or AgentName.GENERAL,
            answer=self.answer or "",
            citations=self.evidence,
            tool_executions=self.tool_executions,
            needs_clarification=self.needs_clarification,
            abstained=self.abstained,
        )


class AgentResponse(Schema):
    """Typed output contract shared by all workers (FR-027)."""

    agent: AgentName
    answer: str = Field(min_length=1)
    citations: list[SourceCitation] = Field(default_factory=list)
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    needs_clarification: bool = False
    abstained: bool = False
