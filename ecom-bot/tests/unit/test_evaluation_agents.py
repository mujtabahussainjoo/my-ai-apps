"""Tests for the routing/tool-selection evaluation harness (FR-055)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.evaluation.routing import (
    RoutingEvaluator,
    load_routing_dataset,
    render_routing_report,
    score_routing_case,
)
from ecommerce_support.schemas import (
    AgentState,
    RoutingEvalCase,
    RoutingEvalDataset,
    RoutingEvalReport,
)
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus


class _ScriptedRunner:
    """Returns a scripted agent per call so accuracy math is predictable."""

    def __init__(self, agents: list[AgentName | None]) -> None:
        self._agents = list(agents)

    async def ainvoke(self, state: AgentState) -> AgentState:
        agent = self._agents.pop(0)
        return AgentState(
            conversation_id=state.conversation_id, message=state.message, selected_agent=agent
        )


def test_load_routing_dataset_missing_file() -> None:
    with pytest.raises(ConfigurationError):
        load_routing_dataset("/nonexistent/routing.yaml")


def test_load_routing_dataset_invalid(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("cases: []\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_routing_dataset(path)


def test_load_bundled_dataset() -> None:
    dataset = load_routing_dataset()
    assert dataset.version
    assert dataset.cases
    assert {case.expected_agent for case in dataset.cases} >= {"order", "policy", "general"}


def test_score_routing_case_exact_match() -> None:
    case = RoutingEvalCase(id="c1", message="Where is my order ord-1?", expected_agent="order")
    state = AgentState(conversation_id="c1", message="x", selected_agent=AgentName.ORDER)
    score = score_routing_case(case, state)
    assert score.routing_correct == 1.0
    assert score.tool_selection_correct == 1.0
    assert score.passed is True


def test_score_routing_case_mismatch() -> None:
    case = RoutingEvalCase(
        id="c1", message="hello", expected_agent="general", expected_tools=["search_products"]
    )
    state = AgentState(conversation_id="c1", message="hello", selected_agent=AgentName.PRODUCT)
    score = score_routing_case(case, state)
    assert score.routing_correct == 0.0
    assert score.tool_selection_correct == 0.0
    assert score.passed is False
    assert score.selected_agent == "product"


def test_tool_selection_order_insensitive() -> None:
    case = RoutingEvalCase(
        id="c1", message="x", expected_agent="order", expected_tools=["get_order", "list_orders"]
    )
    from ecommerce_support.schemas import ToolExecution

    state = AgentState(
        conversation_id="c1",
        message="x",
        selected_agent=AgentName.ORDER,
        tool_executions=[
            ToolExecution(
                call_id="1", tool_name="list_orders", status=ToolCallStatus.OK, summary=""
            ),
            ToolExecution(call_id="2", tool_name="get_order", status=ToolCallStatus.OK, summary=""),
        ],
    )
    assert score_routing_case(case, state).tool_selection_correct == 1.0


async def test_evaluator_aggregates_accuracy() -> None:
    dataset = RoutingEvalDataset(
        version="v1",
        cases=[
            RoutingEvalCase(id="a", message="Where is my order?", expected_agent="order"),
            RoutingEvalCase(id="b", message="hello", expected_agent="general"),
        ],
    )
    report = await RoutingEvaluator(_ScriptedRunner([AgentName.ORDER, AgentName.GENERAL])).evaluate(
        dataset
    )
    assert isinstance(report, RoutingEvalReport)
    assert report.case_count == 2
    assert report.routing_accuracy == 1.0
    assert report.tool_selection_accuracy == 1.0
    assert report.pass_rate == 1.0


async def test_evaluator_reports_partial_accuracy() -> None:
    dataset = RoutingEvalDataset(
        version="v1",
        cases=[
            RoutingEvalCase(id="a", message="Where is my order?", expected_agent="order"),
            RoutingEvalCase(id="b", message="hello", expected_agent="general"),
        ],
    )
    report = await RoutingEvaluator(_ScriptedRunner([AgentName.ORDER, AgentName.PRODUCT])).evaluate(
        dataset
    )
    assert report.routing_accuracy == 0.5
    assert report.pass_rate == 0.5


def test_render_routing_report_mentions_metrics() -> None:
    report = RoutingEvalReport(
        dataset_version="v1",
        case_count=1,
        routing_accuracy=1.0,
        tool_selection_accuracy=1.0,
        pass_rate=1.0,
        notes="baseline",
    )
    text = render_routing_report(report)
    assert "routing_accuracy=1.000" in text
    assert "baseline" in text
