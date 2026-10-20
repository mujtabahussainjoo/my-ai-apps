"""Security tests: account ownership is structural and no secrets leak (TASK-026, SEC-002/SEC-010)."""

from __future__ import annotations

import pytest

from ecommerce_support.agents import AccountWorker
from ecommerce_support.core.exceptions import AuthenticationError
from ecommerce_support.integrations import InMemoryAccountAdapter
from ecommerce_support.schemas import UserProfile
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName
from ecommerce_support.tools import create_account_registry
from ecommerce_support.tools.audit import RecordingAuditHook

pytestmark = pytest.mark.security

_SECRET_KEYS = {"password", "password_hash", "token", "access_token", "secret", "api_key", "ssn"}


def _adapter() -> InMemoryAccountAdapter:
    return InMemoryAccountAdapter(
        profiles=[
            UserProfile(user_id="cust-1", email="ada@example.com", display_name="Ada"),
            UserProfile(user_id="cust-2", email="grace@example.com", display_name="Grace"),
        ],
        order_counts={"cust-1": 1, "cust-2": 5},
    )


def _ctx(user_id: str | None) -> ToolContext:
    return ToolContext(agent=AgentName.ACCOUNT, user_id=user_id, conversation_id="conv-1")


async def test_caller_cannot_target_another_account() -> None:
    """The tools accept no user identifier, so a caller always gets their own account."""
    registry = create_account_registry(_adapter())
    result = await registry.invoke("get_profile", {}, context=_ctx("cust-2"))
    assert result.output is not None
    assert result.output["profile"]["user_id"] == "cust-2"
    assert "ada@example.com" not in str(result.output)


async def test_profile_output_carries_no_secret_fields() -> None:
    registry = create_account_registry(_adapter())
    result = await registry.invoke("get_account_summary", {}, context=_ctx("cust-1"))
    assert result.output is not None
    assert _SECRET_KEYS.isdisjoint(result.output["profile"].keys())


async def test_anonymous_access_is_denied_and_audited() -> None:
    hook = RecordingAuditHook()
    registry = create_account_registry(_adapter(), audit_hook=hook)
    with pytest.raises(AuthenticationError):
        await registry.invoke("get_profile", {}, context=_ctx(None))
    assert "tool.unauthenticated" in hook.event_types()


async def test_audit_events_do_not_contain_pii() -> None:
    hook = RecordingAuditHook()
    registry = create_account_registry(_adapter(), audit_hook=hook)
    worker = AccountWorker(registry)
    await worker.get_profile(context=_ctx("cust-1"))
    blob = str([event.detail for event in hook.events])
    assert "ada@example.com" not in blob
