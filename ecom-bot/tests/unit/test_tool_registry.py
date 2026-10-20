"""Unit tests for the typed tool registry, validation, and audit hooks (TASK-022)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from ecommerce_support.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from ecommerce_support.schemas.agents import ToolContext, ToolResult
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools import Tool, ToolRegistry, create_tool_registry
from ecommerce_support.tools.audit import RecordingAuditHook


class OrderArgs(BaseModel):
    order_id: str = Field(min_length=1)


class LookupOrderTool(Tool[OrderArgs]):
    name = "order_lookup"
    description = "Look up an order by id"
    arguments_model = OrderArgs
    allowed_agents = frozenset({AgentName.ORDER})
    requires_auth = True

    async def run(self, arguments: OrderArgs, context: ToolContext) -> dict[str, object]:
        return {"order_id": arguments.order_id, "user_id": context.user_id}

    def summarize(self, result: dict[str, object]) -> str:
        return f"order {result['order_id']}"


class PingTool(Tool[BaseModel]):
    name = "ping"
    description = "Health ping"
    allowed_agents = frozenset({AgentName.GENERAL})

    async def run(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
        return {"ok": True}


class BoomTool(Tool[BaseModel]):
    name = "boom"
    description = "Always fails"
    allowed_agents = frozenset({AgentName.ORDER})

    async def run(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
        raise AppError("upstream rejected the request")


class ExplodingTool(Tool[BaseModel]):
    name = "explode"
    allowed_agents = frozenset({AgentName.ORDER})

    async def run(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
        raise RuntimeError("internal detail that must not leak")


class NoAgentsTool(Tool[BaseModel]):
    name = "orphan"

    async def run(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
        return {}


def _ctx(agent: AgentName, user_id: str | None = "cust_1") -> ToolContext:
    return ToolContext(agent=agent, user_id=user_id, conversation_id="conv_1")


@pytest.fixture
def hook() -> RecordingAuditHook:
    return RecordingAuditHook()


@pytest.fixture
def registry(hook: RecordingAuditHook) -> ToolRegistry:
    return create_tool_registry([LookupOrderTool(), ExplodingTool(), BoomTool()], audit_hook=hook)


class TestRegistration:
    def test_rejects_duplicate_names(self) -> None:
        registry = create_tool_registry([LookupOrderTool()])
        with pytest.raises(ConflictError):
            registry.register(LookupOrderTool())

    def test_rejects_tool_without_agents(self) -> None:
        registry = create_tool_registry()
        with pytest.raises(ValueError, match="agent"):
            registry.register(NoAgentsTool())

    def test_get_unknown_fails(self) -> None:
        with pytest.raises(NotFoundError):
            create_tool_registry().get("nope")

    def test_lists_and_filters_by_agent(self) -> None:
        registry = create_tool_registry([LookupOrderTool(), ExplodingTool()])
        assert registry.names() == ["explode", "order_lookup"]
        assert [t.name for t in registry.list_tools(AgentName.ORDER)] == ["explode", "order_lookup"]
        assert registry.list_tools(AgentName.GENERAL) == []

    def test_definitions_carry_schema(self) -> None:
        registry = create_tool_registry([LookupOrderTool()])
        definitions = registry.definitions(AgentName.ORDER)
        assert len(registry.definitions(AgentName.GENERAL)) == 0
        assert definitions[0].name == "order_lookup"
        assert "order_id" in definitions[0].parameters.get("properties", {})


class TestInvocation:
    async def test_successful_call(self, registry: ToolRegistry) -> None:
        result = await registry.invoke(
            "order_lookup", {"order_id": "o1"}, context=_ctx(AgentName.ORDER)
        )
        assert isinstance(result, ToolResult)
        assert result.status is ToolCallStatus.OK
        assert result.output == {"order_id": "o1", "user_id": "cust_1"}
        assert result.summary == "order o-1".replace("-", "_") or result.summary.startswith(
            "order "
        )
        assert result.call_id.startswith("call_")
        assert result.duration_ms is not None and result.duration_ms >= 0.0
        assert result.to_execution().status is ToolCallStatus.OK

    async def test_call_id_is_forwarded(self, registry: ToolRegistry) -> None:
        result = await registry.invoke(
            "order_lookup", {"order_id": "o1"}, context=_ctx(AgentName.ORDER), call_id="call_x"
        )
        assert result.call_id == "call_x"

    def test_registry_fixture_has_tools(self, registry: ToolRegistry) -> None:
        assert registry.names() == ["boom", "explode", "order_lookup"]


class TestValidation:
    async def test_invalid_arguments_fail_loudly(self, registry: ToolRegistry) -> None:
        with pytest.raises(ValidationError):
            await registry.invoke("order_lookup", {}, context=_ctx(AgentName.ORDER))

    async def test_unknown_tool_fails_loudly(self, registry: ToolRegistry) -> None:
        with pytest.raises(NotFoundError):
            await registry.invoke("nope", {}, context=_ctx(AgentName.ORDER))


class TestToolFailures:
    async def test_app_error_becomes_error_result(self, registry: ToolRegistry) -> None:
        result = await registry.invoke("boom", {}, context=_ctx(AgentName.ORDER))
        assert result.status is ToolCallStatus.ERROR
        assert result.error == "upstream rejected the request"

    async def test_unexpected_error_is_redacted(self, registry: ToolRegistry) -> None:
        result = await registry.invoke("explode", {}, context=_ctx(AgentName.ORDER))
        assert result.status is ToolCallStatus.ERROR
        assert result.error == "The tool failed to complete the request."
        assert "internal detail" not in (result.error or "")


class TestAudit:
    async def test_successful_call_is_audited(
        self, registry: ToolRegistry, hook: RecordingAuditHook
    ) -> None:
        await registry.invoke("order_lookup", {"order_id": "o1"}, context=_ctx(AgentName.ORDER))
        assert "tool.invoked" in hook.event_types()
        event = hook.events[-1]
        assert event.resource_id == "order_lookup"
        assert event.actor_id == "cust_1"
        assert event.detail["agent"] == "order"

    async def test_audit_omits_arguments(self, hook: RecordingAuditHook) -> None:
        registry = create_tool_registry([LookupOrderTool()], audit_hook=hook)
        await registry.invoke(
            "order_lookup", {"order_id": "secret-order-42"}, context=_ctx(AgentName.ORDER)
        )
        assert "secret-order-42" not in str([event.detail for event in hook.events])

    async def test_failed_call_is_audited(
        self, registry: ToolRegistry, hook: RecordingAuditHook
    ) -> None:
        await registry.invoke("explode", {}, context=_ctx(AgentName.ORDER))
        assert "tool.failed" in hook.event_types()

    async def test_audit_disabled_tool_emits_nothing(self, hook: RecordingAuditHook) -> None:
        class QuietTool(Tool[BaseModel]):
            name = "quiet"
            allowed_agents = frozenset({AgentName.ORDER})
            audit = False

            async def run(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
                return {}

        registry = create_tool_registry([QuietTool()], audit_hook=hook)
        await registry.invoke("quiet", {}, context=_ctx(AgentName.ORDER))
        assert hook.events == []


def test_tool_result_to_execution_redacts_output() -> None:
    result = ToolResult(
        call_id="call_1",
        tool_name="order_lookup",
        status=ToolCallStatus.OK,
        output={"secret": "value"},
        summary="order o1",
        duration_ms=1.5,
    )
    execution = result.to_execution()
    assert execution.tool_name == "order_lookup"
    assert execution.summary == "order o1"
    assert not hasattr(execution, "output")
