"""Agent routing / tool-selection evaluation (FR-055).

Runs a versioned set of messages through an agent runner (the LangGraph graph in production,
a deterministic fake in tests) and scores:

- **intent routing accuracy** — did the router select the expected agent?
- **tool selection accuracy** — did the worker call exactly the expected tools?

Both are Should-level FR-055 baseline metrics. No customer text is persisted by this harness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError as PydanticValidationError

from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.schemas import (
    AgentState,
    RoutingCaseScore,
    RoutingEvalCase,
    RoutingEvalDataset,
    RoutingEvalReport,
)

DEFAULT_ROUTING_DATASET = Path("evals/routing_dataset.yaml")

_YAML_SUFFIXES = {".yaml", ".yml"}


class AgentRunner(Protocol):
    """Anything that can execute one agent turn (graph or fake)."""

    async def ainvoke(self, state: AgentState) -> AgentState: ...


def load_routing_dataset(path: str | Path | None = None) -> RoutingEvalDataset:
    """Load and validate a versioned routing eval dataset (``.yaml``/``.yml``/``.json``)."""
    dataset_path = Path(path) if path is not None else DEFAULT_ROUTING_DATASET
    if not dataset_path.is_file():
        raise ConfigurationError(
            "Routing eval dataset not found.", details={"path": str(dataset_path)}
        )
    suffix = dataset_path.suffix.lower()
    text = dataset_path.read_text(encoding="utf-8")
    try:
        if suffix == ".json":
            data = json.loads(text)
        elif suffix in _YAML_SUFFIXES:
            data = yaml.safe_load(text)
        else:
            raise ConfigurationError(
                "Unsupported eval dataset format (use .yaml, .yml, or .json).",
                details={"path": str(path)},
            )
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigurationError(
            "Could not parse the routing eval dataset.", details={"path": str(path)}
        ) from exc
    if not isinstance(data, dict):
        raise ConfigurationError(
            "The routing eval dataset must be a mapping with 'version' and 'cases'.",
            details={"path": str(path)},
        )
    try:
        return RoutingEvalDataset.model_validate(data)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            "Invalid routing eval dataset.", details={"errors": exc.error_count()}
        ) from exc


def _selected_agent(state: AgentState) -> str | None:
    return state.selected_agent.value if state.selected_agent is not None else None


def _selected_tools(state: AgentState) -> list[str]:
    return sorted({execution.tool_name for execution in state.tool_executions})


def score_routing_case(case: RoutingEvalCase, state: AgentState) -> RoutingCaseScore:
    """Score one case against the agent state produced for it."""
    agent = _selected_agent(state)
    tools = _selected_tools(state)
    routing_correct = 1.0 if agent == case.expected_agent else 0.0
    expected_tools = sorted(set(case.expected_tools))
    tool_selection_correct = 1.0 if tools == expected_tools else 0.0
    return RoutingCaseScore(
        case_id=case.id,
        routing_correct=routing_correct,
        tool_selection_correct=tool_selection_correct,
        selected_agent=agent,
        selected_tools=tools,
        passed=routing_correct == 1.0 and tool_selection_correct == 1.0,
        detail={
            "expected_agent": case.expected_agent,
            "expected_tools": expected_tools,
            "error": state.error,
            "needs_clarification": state.needs_clarification,
        },
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class RoutingEvaluator:
    """Runs a routing dataset through an agent runner and aggregates accuracy metrics."""

    def __init__(
        self,
        runner: AgentRunner,
        *,
        tenant_id: str = "default",
        notes: str = "",
    ) -> None:
        self._runner = runner
        self._tenant_id = tenant_id
        self._notes = notes

    async def evaluate(self, dataset: RoutingEvalDataset) -> RoutingEvalReport:
        scores: list[RoutingCaseScore] = []
        for case in dataset.cases:
            state = AgentState(
                conversation_id=f"eval-{case.id}",
                user_id=case.user_id,
                tenant_id=self._tenant_id,
                message=case.message,
            )
            result = await self._runner.ainvoke(state)
            scores.append(score_routing_case(case, result))
        return RoutingEvalReport(
            dataset_version=dataset.version,
            case_count=len(scores),
            routing_accuracy=_mean([s.routing_correct for s in scores]),
            tool_selection_accuracy=_mean([s.tool_selection_correct for s in scores]),
            pass_rate=_mean([1.0 if s.passed else 0.0 for s in scores]),
            scores=scores,
            notes=self._notes,
        )


def render_routing_report(report: RoutingEvalReport) -> str:
    """Render a human-readable routing report."""
    lines = [
        f"Routing evaluation — dataset {report.dataset_version} ({report.case_count} cases)",
        f"  routing_accuracy={report.routing_accuracy:.3f}  "
        f"tool_selection_accuracy={report.tool_selection_accuracy:.3f}  "
        f"pass_rate={report.pass_rate:.3f}",
    ]
    for score in report.scores:
        lines.append(
            f"  - {score.case_id}: agent={score.selected_agent} "
            f"tools={','.join(score.selected_tools) or '-'} "
            f"{'PASS' if score.passed else 'FAIL'}"
        )
    if report.notes:
        lines.append(f"  note: {report.notes}")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_ROUTING_DATASET",
    "AgentRunner",
    "RoutingEvaluator",
    "load_routing_dataset",
    "render_routing_report",
    "score_routing_case",
]
