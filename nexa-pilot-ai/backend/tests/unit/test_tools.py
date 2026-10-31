"""Tool registry, permission and approval-gate tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from nexapilot.agents.permissions import (
    FS_WRITE,
    SHELL_EXEC,
    WORKFLOW_PERMISSIONS,
    tools_for_workflow,
)
from nexapilot.core.errors import PermissionDeniedError
from nexapilot.tools.base import (
    SimpleTool,
    ToolContext,
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    execute_tool,
)
from nexapilot.tools.registry import build_default_registry


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = "x"


class _Out(BaseModel):
    echoed: str


async def _handler(args: BaseModel, ctx: ToolContext) -> BaseModel:
    return _Out(echoed=getattr(args, "value", ""))


def _tool(name: str, **spec_kwargs: Any) -> SimpleTool:
    spec = ToolSpec(
        name=name,
        purpose="test tool",
        input_model=_In,
        output_model=_Out,
        **spec_kwargs,
    )
    return SimpleTool(spec, _handler)


def test_default_registry_has_no_duplicate_names() -> None:
    registry = build_default_registry()
    names = [tool.spec.name for tool in registry.all()]
    assert len(names) == len(set(names))
    assert len(names) >= 20


#: The workflow's approval matrix (spec section 10): these exact actions must be
#: gated in code, not by prompt wording.
APPROVAL_REQUIRED_TOOLS = {
    "send_email": "email.send",
    "forward_email": "email.forward",
    "delete_email": "email.delete",
    "create_event": "calendar.create_event",
    "place_order": "finance.place_order",
}


def test_spec_approval_matrix_is_enforced() -> None:
    registry = build_default_registry()
    for name, action in APPROVAL_REQUIRED_TOOLS.items():
        tool = registry.get(name)
        assert tool.spec.requires_approval, f"{name} must require approval"
        assert tool.spec.approval_action == action
        assert tool.spec.side_effects


def test_workspace_bounded_tools_do_not_need_approval() -> None:
    """Writes inside the authorised workspace and allowlisted dev commands are
    path/binary-restricted instead of approval-gated (spec 6.6)."""
    registry = build_default_registry()
    for name in ("write_file", "run_tests"):
        tool = registry.get(name)
        assert tool.spec.side_effects
        assert not tool.spec.requires_approval
        assert tool.spec.risk in (ToolRisk.LOW, ToolRisk.MEDIUM)


def test_high_risk_tools_declare_approval() -> None:
    registry = build_default_registry()
    for tool in registry.all():
        if tool.spec.risk is ToolRisk.HIGH:
            assert tool.spec.requires_approval, f"{tool.spec.name} is HIGH risk but ungated"
            assert tool.spec.approval_action


def test_workflow_permission_declarations_are_consistent() -> None:
    registry = build_default_registry()
    known = {tool.spec.name for tool in registry.all()}
    for workflow, entry in WORKFLOW_PERMISSIONS.items():
        declared = set(entry.tools)
        assert declared <= known, f"{workflow} declares unknown tools: {declared - known}"
        assert set(tools_for_workflow(workflow)) == declared


async def test_execute_tool_rejects_missing_permission(container: Any) -> None:
    registry = ToolRegistry()
    registry.register(_tool("write_thing", permissions=frozenset({FS_WRITE}), side_effects=True))
    ctx = ToolContext(
        container=container,
        session=None,
        granted_permissions=frozenset(),  # no FS_WRITE
    )
    with pytest.raises(PermissionDeniedError):
        await execute_tool(registry.get("write_thing"), {"value": "y"}, ctx)


async def test_execute_tool_allows_granted_permission(container: Any) -> None:
    registry = ToolRegistry()
    registry.register(_tool("write_thing", permissions=frozenset({FS_WRITE}), side_effects=True))
    ctx = ToolContext(container=container, session=None, granted_permissions=frozenset({FS_WRITE}))
    result = await execute_tool(registry.get("write_thing"), {"value": "y"}, ctx)
    assert result.echoed == "y"


async def test_execute_tool_enforces_timeout(container: Any) -> None:
    from nexapilot.core.errors import ToolTimeoutError

    async def slow(args: BaseModel, ctx: ToolContext) -> BaseModel:
        await asyncio.sleep(5)
        return _Out(echoed="never")

    registry = ToolRegistry()
    registry.register(
        SimpleTool(
            ToolSpec(
                name="slow_tool",
                purpose="slow",
                input_model=_In,
                output_model=_Out,
                timeout_seconds=0.05,
            ),
            slow,
        )
    )
    ctx = ToolContext(container=container, session=None)
    with pytest.raises(ToolTimeoutError):
        await execute_tool(registry.get("slow_tool"), {}, ctx)


async def test_execute_tool_rejects_invalid_arguments(container: Any) -> None:
    from nexapilot.core.errors import ValidationError

    registry = ToolRegistry()
    registry.register(_tool("echo"))
    ctx = ToolContext(container=container, session=None)
    with pytest.raises(ValidationError):
        await execute_tool(registry.get("echo"), {"wrong": 1}, ctx)


async def test_cancellation_short_circuits_tool_execution(container: Any) -> None:
    from nexapilot.core.errors import RunCancelledError

    registry = ToolRegistry()
    registry.register(_tool("echo"))
    cancel_event = asyncio.Event()
    cancel_event.set()
    ctx = ToolContext(container=container, session=None, cancel_event=cancel_event)
    with pytest.raises(RunCancelledError):
        await execute_tool(registry.get("echo"), {}, ctx)


def test_command_execution_is_permission_gated() -> None:
    registry = build_default_registry()
    shell_tools = [tool for tool in registry.all() if SHELL_EXEC in tool.spec.permissions]
    assert shell_tools
    write_tools = {tool.spec.name for tool in shell_tools if tool.spec.side_effects}
    assert "run_tests" in write_tools
    # ``diff`` is read-only but still needs the shell permission.
    assert all(SHELL_EXEC in tool.spec.permissions for tool in shell_tools)


CALENDAR_APPROVAL_ACTIONS = {
    "create_event": "calendar.create_event",
    "update_event": "calendar.update_event",
    "patch_event": "calendar.patch_event",
    "delete_event": "calendar.delete_event",
    "move_event": "calendar.move_event",
    "quick_add_event": "calendar.quick_add_event",
    "import_event": "calendar.import_event",
    "watch_events": "calendar.watch_events",
    "add_calendar_to_list": "calendar.list_add",
    "update_calendar_list_entry": "calendar.list_update",
    "patch_calendar_list_entry": "calendar.list_patch",
    "remove_calendar_from_list": "calendar.list_remove",
    "watch_calendar_list": "calendar.list_watch",
    "create_calendar": "calendar.create",
    "update_calendar": "calendar.update",
    "patch_calendar": "calendar.patch",
    "delete_calendar": "calendar.delete",
    "clear_calendar": "calendar.clear",
    "transfer_calendar_ownership": "calendar.transfer",
    "create_acl_rule": "calendar.acl_create",
    "update_acl_rule": "calendar.acl_update",
    "patch_acl_rule": "calendar.acl_patch",
    "delete_acl_rule": "calendar.acl_delete",
    "watch_acl": "calendar.acl_watch",
    "watch_settings": "calendar.settings_watch",
    "stop_channel": "calendar.channel_stop",
}


def test_calendar_tools_cover_the_v3_surface() -> None:
    registry = build_default_registry()
    expected = {
        "list_events",
        "search_calendar_events",
        "get_event",
        "list_event_instances",
        "create_event",
        "update_event",
        "patch_event",
        "delete_event",
        "move_event",
        "quick_add_event",
        "import_event",
        "watch_events",
        "query_freebusy",
        "get_calendar_colors",
        "list_calendar_list",
        "get_calendar_list_entry",
        "add_calendar_to_list",
        "update_calendar_list_entry",
        "patch_calendar_list_entry",
        "remove_calendar_from_list",
        "watch_calendar_list",
        "get_calendar",
        "create_calendar",
        "update_calendar",
        "patch_calendar",
        "delete_calendar",
        "clear_calendar",
        "transfer_calendar_ownership",
        "list_acl",
        "get_acl_rule",
        "create_acl_rule",
        "update_acl_rule",
        "patch_acl_rule",
        "delete_acl_rule",
        "watch_acl",
        "list_settings",
        "get_setting",
        "watch_settings",
        "stop_channel",
    }
    assert expected <= {tool.spec.name for tool in registry.all()}


def test_calendar_mutating_tools_are_approval_gated() -> None:
    registry = build_default_registry()
    for name, action in CALENDAR_APPROVAL_ACTIONS.items():
        tool = registry.get(name)
        assert tool.spec.requires_approval, f"{name} must require approval"
        assert tool.spec.approval_action == action
        assert tool.spec.side_effects
        assert tool.spec.permissions
    calendar_tools = {
        tool.spec.name
        for tool in registry.all()
        if tool.spec.name in CALENDAR_APPROVAL_ACTIONS and not tool.spec.requires_approval
    }
    assert not calendar_tools
