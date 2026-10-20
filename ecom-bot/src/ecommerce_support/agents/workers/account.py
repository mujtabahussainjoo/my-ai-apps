"""Account worker: authorized profile/account answers for the signed-in customer (FR-023).

Framework-free facade over the account tools. The tools read the caller's identity from
``ToolContext`` and the worker only formats the returned non-secret profile fields, so neither the
model nor the caller can target another customer or surface credentials.
"""

from __future__ import annotations

from collections.abc import Callable

from ecommerce_support.schemas.agents import AgentResponse, ToolContext
from ecommerce_support.schemas.enums import ToolCallStatus
from ecommerce_support.tools.registry import ToolRegistry

_Render = Callable[[dict[str, object]], str]

_NOT_FOUND_MESSAGE = "I couldn't find an account for you."
_ERROR_MESSAGE = "I ran into a problem looking that up. Please try again."


def _render_profile(output: dict[str, object]) -> str:
    profile = output.get("profile")
    if not isinstance(profile, dict):
        return _ERROR_MESSAGE
    name = profile.get("display_name") or "your account"
    email = profile.get("email")
    text = f"You're signed in as {name}."
    if email:
        text += f" Email on file: {email}."
    return text


def _render_summary(output: dict[str, object]) -> str:
    profile = output.get("profile")
    if not isinstance(profile, dict):
        return _ERROR_MESSAGE
    name = profile.get("display_name") or "your account"
    return f"{name} has {output.get('order_count', 0)} order(s) on file."


class AccountWorker:
    """Typed facade over the account tools for the graph to call."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def get_profile(self, *, context: ToolContext) -> AgentResponse:
        return await self._call("get_profile", context=context, render=_render_profile)

    async def get_summary(self, *, context: ToolContext) -> AgentResponse:
        return await self._call("get_account_summary", context=context, render=_render_summary)

    async def _call(self, name: str, *, context: ToolContext, render: _Render) -> AgentResponse:
        result = await self._registry.invoke(name, {}, context=context)
        execution = result.to_execution()
        if result.status is not ToolCallStatus.OK or result.output is None:
            answer = _NOT_FOUND_MESSAGE if result.error == "Account not found." else _ERROR_MESSAGE
        else:
            answer = render(result.output)
        return AgentResponse(agent=context.agent, answer=answer, tool_executions=[execution])
