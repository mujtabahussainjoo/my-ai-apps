"""Account tools: the signed-in customer's own profile/summary (FR-023/FR-040).

Authorization is structural: the tools take **no** user identifier from the caller and always read
``ToolContext.user_id``. There is therefore no argument an agent or model could supply to reach
another customer's account. Only non-secret profile fields are returned (never passwords/tokens).
"""

from __future__ import annotations

from pydantic import BaseModel

from ecommerce_support.core.exceptions import AuthenticationError, NotFoundError
from ecommerce_support.integrations.account import AccountAdapter
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName
from ecommerce_support.tools.audit import AuditHook
from ecommerce_support.tools.registry import Tool, ToolRegistry, create_tool_registry

_ACCOUNT_AGENTS = frozenset({AgentName.ACCOUNT})


class AccountArgs(BaseModel):
    """Account tools take no caller-supplied identifiers (ownership is implicit)."""


def _require_caller(context: ToolContext) -> str:
    if not context.user_id:
        raise AuthenticationError("This action requires a signed-in customer.")
    return context.user_id


class GetProfileTool(Tool[AccountArgs]):
    """Return the signed-in customer's own profile."""

    name = "get_profile"
    description = "Return the signed-in customer's own account profile."
    arguments_model = AccountArgs
    allowed_agents = _ACCOUNT_AGENTS
    requires_auth = True

    def __init__(self, adapter: AccountAdapter) -> None:
        self._adapter = adapter

    async def run(self, arguments: AccountArgs, context: ToolContext) -> dict[str, object]:
        profile = await self._adapter.get_profile(_require_caller(context))
        if profile is None:
            raise NotFoundError("Account not found.")
        return {"profile": profile.model_dump(mode="json")}

    def summarize(self, result: dict[str, object]) -> str:
        return "fetched account profile"


class GetAccountSummaryTool(Tool[AccountArgs]):
    """Return the signed-in customer's profile plus order count."""

    name = "get_account_summary"
    description = "Return the signed-in customer's account summary (profile + order count)."
    arguments_model = AccountArgs
    allowed_agents = _ACCOUNT_AGENTS
    requires_auth = True

    def __init__(self, adapter: AccountAdapter) -> None:
        self._adapter = adapter

    async def run(self, arguments: AccountArgs, context: ToolContext) -> dict[str, object]:
        user_id = _require_caller(context)
        profile = await self._adapter.get_profile(user_id)
        if profile is None:
            raise NotFoundError("Account not found.")
        return {
            "profile": profile.model_dump(mode="json"),
            "order_count": await self._adapter.order_count(user_id),
        }

    def summarize(self, result: dict[str, object]) -> str:
        return "fetched account summary"


def create_account_registry(
    adapter: AccountAdapter, *, audit_hook: AuditHook | None = None
) -> ToolRegistry:
    """Build a registry containing the account tools bound to ``adapter``."""
    return create_tool_registry(
        [GetProfileTool(adapter), GetAccountSummaryTool(adapter)],
        audit_hook=audit_hook,
    )
