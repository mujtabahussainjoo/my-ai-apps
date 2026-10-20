"""Unit tests for account tools and worker: strict ownership, no secrets (TASK-026)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ecommerce_support.agents import AccountWorker
from ecommerce_support.core.exceptions import AuthenticationError, AuthorizationError, NotFoundError
from ecommerce_support.integrations import InMemoryAccountAdapter
from ecommerce_support.schemas import UserProfile
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools import create_account_registry
from ecommerce_support.tools.account import AccountArgs, GetAccountSummaryTool, GetProfileTool


def _profile(user_id: str, name: str) -> UserProfile:
    return UserProfile(
        user_id=user_id,
        email=f"{user_id}@example.com",
        display_name=name,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.fixture
def adapter() -> InMemoryAccountAdapter:
    return InMemoryAccountAdapter(
        profiles=[_profile("cust-1", "Ada"), _profile("cust-2", "Grace")],
        order_counts={"cust-1": 3, "cust-2": 0},
    )


def _ctx(user_id: str | None = "cust-1", agent: AgentName = AgentName.ACCOUNT) -> ToolContext:
    return ToolContext(agent=agent, user_id=user_id, conversation_id="conv-1")


class TestGetProfileTool:
    async def test_returns_caller_profile(self, adapter: InMemoryAccountAdapter) -> None:
        output = await GetProfileTool(adapter).run(AccountArgs(), _ctx("cust-1"))
        assert output["profile"]["user_id"] == "cust-1"  # type: ignore[index]

    async def test_ignores_no_argument_for_other_user(
        self, adapter: InMemoryAccountAdapter
    ) -> None:
        output = await GetProfileTool(adapter).run(AccountArgs(), _ctx("cust-2"))
        assert output["profile"]["user_id"] == "cust-2"  # type: ignore[index]

    async def test_anonymous_is_rejected(self, adapter: InMemoryAccountAdapter) -> None:
        with pytest.raises(AuthenticationError):
            await GetProfileTool(adapter).run(AccountArgs(), _ctx(None))

    async def test_unknown_account_is_not_found(self, adapter: InMemoryAccountAdapter) -> None:
        with pytest.raises(NotFoundError):
            await GetProfileTool(adapter).run(AccountArgs(), _ctx("nobody"))


class TestGetAccountSummaryTool:
    async def test_includes_order_count(self, adapter: InMemoryAccountAdapter) -> None:
        output = await GetAccountSummaryTool(adapter).run(AccountArgs(), _ctx("cust-1"))
        assert output["order_count"] == 3  # type: ignore[comparison-overlap]


class TestAccountRegistry:
    async def test_only_account_agent_allowed(self, adapter: InMemoryAccountAdapter) -> None:
        registry = create_account_registry(adapter)
        with pytest.raises(AuthorizationError):
            await registry.invoke("get_profile", {}, context=_ctx(agent=AgentName.ORDER))

    async def test_anonymous_through_registry_rejected(
        self, adapter: InMemoryAccountAdapter
    ) -> None:
        registry = create_account_registry(adapter)
        with pytest.raises(AuthenticationError):
            await registry.invoke("get_profile", {}, context=_ctx(None))


class TestAccountWorker:
    @pytest.fixture
    def worker(self, adapter: InMemoryAccountAdapter) -> AccountWorker:
        return AccountWorker(create_account_registry(adapter))

    async def test_profile_answer(self, worker: AccountWorker) -> None:
        response = await worker.get_profile(context=_ctx("cust-1"))
        assert "Ada" in response.answer
        assert response.tool_executions[0].status is ToolCallStatus.OK

    async def test_summary_answer(self, worker: AccountWorker) -> None:
        response = await worker.get_summary(context=_ctx("cust-1"))
        assert "3 order(s)" in response.answer

    async def test_unknown_account_is_polite(self, worker: AccountWorker) -> None:
        response = await worker.get_profile(context=_ctx("nobody"))
        assert response.answer == "I couldn't find an account for you."
