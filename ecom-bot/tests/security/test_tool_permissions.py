"""Security tests: per-agent tool allowlists and authorization (TASK-022, SEC-010).

These assert that the registry is the security boundary — an agent can only call tools on its
allowlist, authentication is enforced in code, and denials are audited without leaking arguments.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from ecommerce_support.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
)
from ecommerce_support.schemas.agents import ToolContext, ToolResult
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools import Tool, ToolRegistry, create_tool_registry
from ecommerce_support.tools.audit import RecordingAuditHook

pytestmark = pytest.mark.security


class OrderLookupArgs(BaseModel):
    order_id: str = Field(min_length=1)


class OrderLookup(Tool[OrderLookupArgs]):
    name = "order_lookup"
    allowed_agents = frozenset({AgentName.ORDER})
    requires_auth = True
    arguments_model = OrderLookupArgs

    async def run(self, arguments: OrderLookupArgs, context: ToolContext) -> dict[str, object]:
        return {"order_id": arguments.order_id}


class AccountLookup(Tool[BaseModel]):
    name = "account_lookup"
    allowed_agents = frozenset({AgentName.ACCOUNT})
    requires_auth = True

    async def run(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
        return {"user_id": context.user_id}


class ProductSearch(Tool[BaseModel]):
    name = "product_search"
    allowed_agents = frozenset({AgentName.PRODUCT})

    async def run(self, arguments: BaseModel, context: ToolContext) -> dict[str, object]:
        return {"results": []}


def _registry(hook: RecordingAuditHook) -> ToolRegistry:
    return create_tool_registry([OrderLookup(), AccountLookup(), ProductSearch()], audit_hook=hook)


class TestAgentAllowlist:
    async def test_allowed_agent_can_call(self) -> None:
        hook = RecordingAuditHook()
        result = await _registry(hook).invoke(
            "order_lookup",
            {"order_id": "o1"},
            context=ToolContext(agent=AgentName.ORDER, user_id="cust_1"),
        )
        assert isinstance(result, ToolResult)
        assert result.status is ToolCallStatus.OK

    async def test_disallowed_agent_is_denied(self) -> None:
        hook = RecordingAuditHook()
        with pytest.raises(AuthorizationError):
            await _registry(hook).invoke(
                "order_lookup",
                {"order_id": "o1"},
                context=ToolContext(agent=AgentName.PRODUCT, user_id="cust_1"),
            )

    async def test_cross_agent_tools_are_isolated(self) -> None:
        hook = RecordingAuditHook()
        registry = _registry(hook)
        with pytest.raises(AuthorizationError):
            await registry.invoke("account_lookup", {}, context=ToolContext(agent=AgentName.ORDER))
        with pytest.raises(AuthorizationError):
            await registry.invoke("product_search", {}, context=ToolContext(agent=AgentName.ORDER))

    async def test_definition_visibility_respects_allowlist(self) -> None:
        registry = _registry(RecordingAuditHook())
        order_tools = {definition.name for definition in registry.definitions(AgentName.ORDER)}
        assert order_tools == {"order_lookup"}
        assert registry.definitions(AgentName.PRODUCT)[0].name == "product_search"


class TestAuthentication:
    async def test_missing_identity_is_rejected(self) -> None:
        hook = RecordingAuditHook()
        with pytest.raises(AuthenticationError):
            await _registry(hook).invoke(
                "order_lookup",
                {"order_id": "o1"},
                context=ToolContext(agent=AgentName.ORDER, user_id=None),
            )

    async def test_public_tool_allows_anonymous(self) -> None:
        hook = RecordingAuditHook()
        result = await _registry(hook).invoke(
            "product_search", {}, context=ToolContext(agent=AgentName.PRODUCT, user_id=None)
        )
        assert result.status is ToolCallStatus.OK


class TestDenialAuditing:
    async def test_denied_call_is_audited(self) -> None:
        hook = RecordingAuditHook()
        with pytest.raises(AuthorizationError):
            await _registry(hook).invoke(
                "order_lookup",
                {"order_id": "secret-42"},
                context=ToolContext(agent=AgentName.PRODUCT, user_id="cust_1"),
            )
        assert "tool.denied" in hook.event_types()

    async def test_denial_audit_omits_arguments(self) -> None:
        hook = RecordingAuditHook()
        with pytest.raises(AuthorizationError):
            await _registry(hook).invoke(
                "order_lookup",
                {"order_id": "secret-42"},
                context=ToolContext(agent=AgentName.PRODUCT, user_id="cust_1"),
            )
        assert "secret-42" not in str([event.detail for event in hook.events])

    async def test_unauthenticated_call_is_audited(self) -> None:
        hook = RecordingAuditHook()
        with pytest.raises(AuthenticationError):
            await _registry(hook).invoke(
                "order_lookup", {"order_id": "o1"}, context=ToolContext(agent=AgentName.ORDER)
            )
        assert "tool.unauthenticated" in hook.event_types()


class TestUnknownTools:
    async def test_unknown_tool_cannot_be_invoked(self) -> None:
        with pytest.raises(NotFoundError):
            await _registry(RecordingAuditHook()).invoke(
                "admin_delete_everything", {}, context=ToolContext(agent=AgentName.SUPERAGENT)
            )

    async def test_agent_cannot_see_tools_it_lacks(self) -> None:
        registry = _registry(RecordingAuditHook())
        visible = {definition.name for definition in registry.definitions(AgentName.ACCOUNT)}
        assert visible == {"account_lookup"}
