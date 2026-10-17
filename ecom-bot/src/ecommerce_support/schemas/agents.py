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


class ToolExecution(Schema):
    """Audit record of a single tool invocation (redacted summary only)."""

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: ToolCallStatus
    summary: str = ""
    duration_ms: float | None = Field(default=None, ge=0.0)


class RoutingDecision(Schema):
    """Result of intent classification and agent selection (FR-015-FR-018)."""

    intent: Intent
    agent: AgentName
    requires_auth: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str = ""


class AgentState(Schema):
    """Typed workflow state tracked across graph nodes (FR-018)."""

    conversation_id: str = Field(min_length=1)
    user_id: str | None = None
    intent: Intent | None = None
    selected_agent: AgentName | None = None
    requires_auth: bool = False
    retry_count: int = Field(default=0, ge=0)
    iterations: int = Field(default=0, ge=0)
    resolution_state: ResolutionOutcome | None = None
    ticket_status: TicketStatus | None = None
    evidence: list[SourceCitation] = Field(default_factory=list)
    attempts: list[str] = Field(default_factory=list)


class AgentResponse(Schema):
    """Typed output contract shared by all workers (FR-027)."""

    agent: AgentName
    answer: str = Field(min_length=1)
    citations: list[SourceCitation] = Field(default_factory=list)
    tool_executions: list[ToolExecution] = Field(default_factory=list)
    needs_clarification: bool = False
    abstained: bool = False
