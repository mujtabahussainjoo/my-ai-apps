"""RAG evaluation result contracts (FR-055)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ecommerce_support.schemas.common import Schema


class EvalResultCreate(Schema):
    """A single metric observation for an evaluation case."""

    dataset_version: str = Field(min_length=1, max_length=64)
    case_id: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0.0, le=1.0)
    detail: dict[str, Any] = Field(default_factory=dict)


class EvalResult(Schema):
    """A persisted evaluation result."""

    id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1, max_length=64)
    case_id: str = Field(min_length=1, max_length=64)
    metric: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0.0, le=1.0)
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class RagEvalCase(Schema):
    """One versioned RAG evaluation case (FR-055)."""

    id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1)
    expected_documents: list[str] = Field(default_factory=list)
    expected_quote: str | None = None
    should_abstain: bool = False


class RagEvalDataset(Schema):
    """A versioned set of RAG evaluation cases."""

    version: str = Field(min_length=1, max_length=64)
    cases: list[RagEvalCase] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when the dataset has no cases."""
        return not self.cases


class RagCaseScore(Schema):
    """Per-case retrieval/groundedness scores."""

    case_id: str = Field(min_length=1)
    recall: float = Field(ge=0.0, le=1.0)
    groundedness: float = Field(ge=0.0, le=1.0)
    abstention_correct: float = Field(ge=0.0, le=1.0)
    citation_count: int = Field(ge=0)
    abstained: bool
    passed: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class RagEvalReport(Schema):
    """Aggregate RAG evaluation report for a dataset version."""

    dataset_version: str = Field(min_length=1, max_length=64)
    case_count: int = Field(ge=0)
    mean_recall: float = Field(ge=0.0, le=1.0)
    mean_groundedness: float = Field(ge=0.0, le=1.0)
    abstention_accuracy: float = Field(ge=0.0, le=1.0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    scores: list[RagCaseScore] = Field(default_factory=list)
    notes: str = ""


class RoutingEvalCase(Schema):
    """One versioned routing/tool-selection evaluation case (FR-055)."""

    id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1)
    expected_agent: str = Field(min_length=1, max_length=40)
    expected_tools: list[str] = Field(default_factory=list)
    user_id: str | None = None


class RoutingEvalDataset(Schema):
    """A versioned set of routing/tool-selection evaluation cases."""

    version: str = Field(min_length=1, max_length=64)
    cases: list[RoutingEvalCase] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True when the dataset has no cases."""
        return not self.cases


class RoutingCaseScore(Schema):
    """Per-case intent-routing and tool-selection scores."""

    case_id: str = Field(min_length=1)
    routing_correct: float = Field(ge=0.0, le=1.0)
    tool_selection_correct: float = Field(ge=0.0, le=1.0)
    selected_agent: str | None = None
    selected_tools: list[str] = Field(default_factory=list)
    passed: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class RoutingEvalReport(Schema):
    """Aggregate routing/tool-selection evaluation report (FR-055)."""

    dataset_version: str = Field(min_length=1, max_length=64)
    case_count: int = Field(ge=0)
    routing_accuracy: float = Field(ge=0.0, le=1.0)
    tool_selection_accuracy: float = Field(ge=0.0, le=1.0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    scores: list[RoutingCaseScore] = Field(default_factory=list)
    notes: str = ""
