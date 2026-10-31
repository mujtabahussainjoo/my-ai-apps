"""Graph state shared by all agent workflows."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

WorkflowName = Literal[
    "general",
    "research",
    "travel",
    "email",
    "calendar",
    "finance",
    "coding",
]

ALL_WORKFLOWS: tuple[str, ...] = (
    "general",
    "research",
    "travel",
    "email",
    "calendar",
    "finance",
    "coding",
)


class AgentState(TypedDict, total=False):
    """State carried through the graph.

    Only plain JSON-serialisable values are stored so that checkpoints remain
    portable and the API can serialise a run without extra conversion.
    """

    messages: list[dict[str, Any]]
    workflow: str
    user_request: str
    conversation_id: str
    task_run_id: str
    provider_id: str
    model: str
    thread_id: str
    iteration: int
    citations: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    final_answer: str
    status: str
    error: str
    partial: bool
    metadata: dict[str, Any]
