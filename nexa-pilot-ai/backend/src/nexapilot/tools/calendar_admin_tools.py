"""Google Calendar administration tools.

Covers Calendars, CalendarList, Acl, Settings and Channels. Every mutating or
push-channel operation requires explicit approval; reads stay ungated but still
need the ``calendar:read`` permission.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nexapilot.agents.permissions import CALENDAR_READ, CALENDAR_WRITE
from nexapilot.tools.base import Tool, ToolContext, ToolRisk, ToolSpec
from nexapilot.tools.calendar_tools import ChannelInput, ChannelOutput, _channel_body

_CALENDAR_WRITE = frozenset({CALENDAR_READ, CALENDAR_WRITE})
_CALENDAR_READ = frozenset({CALENDAR_READ})


class CalendarDataOutput(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class CalendarListOutput(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0
    next_page_token: str = ""
    next_sync_token: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class StatusOutput(BaseModel):
    status: str = "ok"


class _AccountInput(BaseModel):
    account_id: str = Field(default="", max_length=64)


class _CalendarInput(_AccountInput):
    calendar_id: str = Field(default="primary", max_length=300)


class ListCalendarListInput(_AccountInput):
    max_results: int = Field(default=250, ge=1, le=250)
    page_token: str = Field(default="", max_length=4000)
    min_access_role: str = Field(default="", max_length=40)
    show_deleted: bool = False
    show_hidden: bool = False
    sync_token: str = Field(default="", max_length=4000)


class GetCalendarListEntryInput(_CalendarInput):
    pass


class InsertCalendarListEntryInput(_AccountInput):
    body: dict[str, Any] = Field(min_length=1)
    color_rgb_format: bool = False


class UpdateCalendarListEntryInput(_CalendarInput):
    body: dict[str, Any] = Field(min_length=1)


class PatchCalendarListEntryInput(UpdateCalendarListEntryInput):
    pass


class DeleteCalendarListEntryInput(_CalendarInput):
    pass


class WatchCalendarListInput(ChannelInput):
    pass


class GetCalendarInput(_CalendarInput):
    pass


class InsertCalendarInput(_AccountInput):
    body: dict[str, Any] = Field(min_length=1)


class UpdateCalendarInput(_CalendarInput):
    body: dict[str, Any] = Field(min_length=1)


class PatchCalendarInput(UpdateCalendarInput):
    pass


class DeleteCalendarInput(_CalendarInput):
    pass


class ClearCalendarInput(_CalendarInput):
    pass


class TransferCalendarInput(_CalendarInput):
    new_data_owner: str = Field(min_length=3, max_length=320)
    use_admin_access: bool = True


class ListAclInput(_CalendarInput):
    max_results: int = Field(default=100, ge=1, le=100)
    page_token: str = Field(default="", max_length=4000)
    show_deleted: bool = False
    sync_token: str = Field(default="", max_length=4000)


class AclRuleInput(_CalendarInput):
    rule_id: str = Field(min_length=1, max_length=300)


class InsertAclRuleInput(_CalendarInput):
    body: dict[str, Any] = Field(min_length=1)
    send_notifications: bool = False


class UpdateAclRuleInput(AclRuleInput):
    body: dict[str, Any] = Field(min_length=1)


class PatchAclRuleInput(UpdateAclRuleInput):
    pass


class WatchAclInput(ChannelInput):
    pass


class ListSettingsInput(_AccountInput):
    max_results: int = Field(default=100, ge=1, le=250)
    page_token: str = Field(default="", max_length=4000)
    sync_token: str = Field(default="", max_length=4000)


class GetSettingInput(_AccountInput):
    setting: str = Field(min_length=1, max_length=200)


class WatchSettingsInput(ChannelInput):
    pass


class StopChannelInput(_AccountInput):
    channel_id: str = Field(min_length=1, max_length=300)
    resource_id: str = Field(min_length=1, max_length=1000)


class ListCalendarListTool(Tool):
    spec = ToolSpec(
        name="list_calendar_list",
        purpose="List the calendars on the connected user's calendar list.",
        input_model=ListCalendarListInput,
        output_model=CalendarListOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ListCalendarListInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        data = await client.list_calendar_list(
            max_results=args.max_results,
            page_token=args.page_token,
            min_access_role=args.min_access_role,
            show_deleted=args.show_deleted,
            show_hidden=args.show_hidden,
            sync_token=args.sync_token,
        )
        return _list_output(data)


class GetCalendarListEntryTool(Tool):
    spec = ToolSpec(
        name="get_calendar_list_entry",
        purpose="Return one calendar from the connected user's calendar list.",
        input_model=GetCalendarListEntryInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, GetCalendarListEntryInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(data=await client.get_calendar_list_entry(args.calendar_id))


class InsertCalendarListEntryTool(Tool):
    spec = ToolSpec(
        name="add_calendar_to_list",
        purpose="Add an existing calendar to the user's calendar list. Requires approval.",
        input_model=InsertCalendarListEntryInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.list_add",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, InsertCalendarListEntryInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        data = await client.insert_calendar_list_entry(
            args.body, color_rgb_format=args.color_rgb_format
        )
        return CalendarDataOutput(data=data)


class UpdateCalendarListEntryTool(Tool):
    spec = ToolSpec(
        name="update_calendar_list_entry",
        purpose="Replace a calendar-list entry. Requires explicit approval.",
        input_model=UpdateCalendarListEntryInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.list_update",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, UpdateCalendarListEntryInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        data = await client.update_calendar_list_entry(args.calendar_id, args.body)
        return CalendarDataOutput(data=data)


class PatchCalendarListEntryTool(Tool):
    spec = ToolSpec(
        name="patch_calendar_list_entry",
        purpose="Partially update a calendar-list entry. Requires approval.",
        input_model=PatchCalendarListEntryInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.list_patch",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, PatchCalendarListEntryInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        data = await client.patch_calendar_list_entry(args.calendar_id, args.body)
        return CalendarDataOutput(data=data)


class DeleteCalendarListEntryTool(Tool):
    spec = ToolSpec(
        name="remove_calendar_from_list",
        purpose="Remove a calendar from the user's calendar list. Requires approval.",
        input_model=DeleteCalendarListEntryInput,
        output_model=StatusOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.list_remove",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, DeleteCalendarListEntryInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        await client.delete_calendar_list_entry(args.calendar_id)
        return StatusOutput(status="removed")


class WatchCalendarListTool(Tool):
    spec = ToolSpec(
        name="watch_calendar_list",
        purpose="Create a push channel for calendar-list changes. Requires approval.",
        input_model=WatchCalendarListInput,
        output_model=ChannelOutput,
        permissions=_CALENDAR_READ,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.list_watch",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, WatchCalendarListInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return ChannelOutput(channel=await client.watch_calendar_list(_channel_body(args)))


class GetCalendarTool(Tool):
    spec = ToolSpec(
        name="get_calendar",
        purpose="Return metadata for a calendar.",
        input_model=GetCalendarInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, GetCalendarInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(data=await client.get_calendar(args.calendar_id))


class InsertCalendarTool(Tool):
    spec = ToolSpec(
        name="create_calendar",
        purpose="Create a secondary calendar. Requires explicit user approval.",
        input_model=InsertCalendarInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.create",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, InsertCalendarInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(data=await client.insert_calendar(args.body))


class UpdateCalendarTool(Tool):
    spec = ToolSpec(
        name="update_calendar",
        purpose="Replace calendar metadata. Requires explicit approval.",
        input_model=UpdateCalendarInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.update",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, UpdateCalendarInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(data=await client.update_calendar(args.calendar_id, args.body))


class PatchCalendarTool(Tool):
    spec = ToolSpec(
        name="patch_calendar",
        purpose="Partially update calendar metadata. Requires approval.",
        input_model=PatchCalendarInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.patch",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, PatchCalendarInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(data=await client.patch_calendar(args.calendar_id, args.body))


class DeleteCalendarTool(Tool):
    spec = ToolSpec(
        name="delete_calendar",
        purpose="Delete a secondary calendar. Requires explicit user approval.",
        input_model=DeleteCalendarInput,
        output_model=StatusOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.delete",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, DeleteCalendarInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        await client.delete_calendar(args.calendar_id)
        return StatusOutput(status="deleted")


class ClearCalendarTool(Tool):
    spec = ToolSpec(
        name="clear_calendar",
        purpose="Delete all events from the primary calendar. Requires approval.",
        input_model=ClearCalendarInput,
        output_model=StatusOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=60.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.clear",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ClearCalendarInput)
        from nexapilot.services.calendar_service import (
            calendar_client,
            clear_calendar_events,
        )

        account, client = calendar_client(ctx, args.account_id)
        await client.clear_calendar(args.calendar_id)
        clear_calendar_events(ctx, account.id)
        ctx.session.flush()
        return StatusOutput(status="cleared")


class TransferCalendarTool(Tool):
    spec = ToolSpec(
        name="transfer_calendar_ownership",
        purpose="Transfer a secondary calendar to another user. Requires approval.",
        input_model=TransferCalendarInput,
        output_model=StatusOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=60.0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.transfer",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, TransferCalendarInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        await client.transfer_calendar_ownership(
            args.calendar_id,
            new_data_owner=args.new_data_owner,
            use_admin_access=args.use_admin_access,
        )
        return StatusOutput(status="transferred")


class ListAclTool(Tool):
    spec = ToolSpec(
        name="list_acl",
        purpose="List the access control rules for a calendar.",
        input_model=ListAclInput,
        output_model=CalendarListOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ListAclInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        data = await client.list_acl(
            calendar_id=args.calendar_id,
            max_results=args.max_results,
            page_token=args.page_token,
            show_deleted=args.show_deleted,
            sync_token=args.sync_token,
        )
        return _list_output(data)


class GetAclRuleTool(Tool):
    spec = ToolSpec(
        name="get_acl_rule",
        purpose="Return one access control rule for a calendar.",
        input_model=AclRuleInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, AclRuleInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(
            data=await client.get_acl_rule(args.rule_id, calendar_id=args.calendar_id)
        )


class InsertAclRuleTool(Tool):
    spec = ToolSpec(
        name="create_acl_rule",
        purpose="Share a calendar by creating an ACL rule. Requires approval.",
        input_model=InsertAclRuleInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.acl_create",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, InsertAclRuleInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(
            data=await client.insert_acl_rule(
                args.body,
                calendar_id=args.calendar_id,
                send_notifications=args.send_notifications,
            )
        )


class UpdateAclRuleTool(Tool):
    spec = ToolSpec(
        name="update_acl_rule",
        purpose="Replace an ACL rule (changes sharing). Requires approval.",
        input_model=UpdateAclRuleInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.acl_update",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, UpdateAclRuleInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(
            data=await client.update_acl_rule(args.rule_id, args.body, calendar_id=args.calendar_id)
        )


class PatchAclRuleTool(Tool):
    spec = ToolSpec(
        name="patch_acl_rule",
        purpose="Partially update an ACL rule. Requires approval.",
        input_model=PatchAclRuleInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.acl_patch",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, PatchAclRuleInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(
            data=await client.patch_acl_rule(args.rule_id, args.body, calendar_id=args.calendar_id)
        )


class DeleteAclRuleTool(Tool):
    spec = ToolSpec(
        name="delete_acl_rule",
        purpose="Remove an ACL rule (revokes sharing). Requires approval.",
        input_model=AclRuleInput,
        output_model=StatusOutput,
        permissions=_CALENDAR_WRITE,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.acl_delete",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, AclRuleInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        await client.delete_acl_rule(args.rule_id, calendar_id=args.calendar_id)
        return StatusOutput(status="deleted")


class WatchAclTool(Tool):
    spec = ToolSpec(
        name="watch_acl",
        purpose="Create a push channel for ACL changes. Requires approval.",
        input_model=WatchAclInput,
        output_model=ChannelOutput,
        permissions=_CALENDAR_READ,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.acl_watch",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, WatchAclInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return ChannelOutput(
            channel=await client.watch_acl(_channel_body(args), calendar_id=args.calendar_id)
        )


class ListSettingsTool(Tool):
    spec = ToolSpec(
        name="list_settings",
        purpose="List the authenticated user's calendar settings.",
        input_model=ListSettingsInput,
        output_model=CalendarListOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, ListSettingsInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        data = await client.list_settings(
            max_results=args.max_results,
            page_token=args.page_token,
            sync_token=args.sync_token,
        )
        return _list_output(data)


class GetSettingTool(Tool):
    spec = ToolSpec(
        name="get_setting",
        purpose="Return one calendar user setting.",
        input_model=GetSettingInput,
        output_model=CalendarDataOutput,
        permissions=_CALENDAR_READ,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, GetSettingInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return CalendarDataOutput(data=await client.get_setting(args.setting))


class WatchSettingsTool(Tool):
    spec = ToolSpec(
        name="watch_settings",
        purpose="Create a push channel for calendar-settings changes. Requires approval.",
        input_model=WatchSettingsInput,
        output_model=ChannelOutput,
        permissions=_CALENDAR_READ,
        side_effects=True,
        timeout_seconds=45.0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="calendar.settings_watch",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, WatchSettingsInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        return ChannelOutput(channel=await client.watch_settings(_channel_body(args)))


class StopChannelTool(Tool):
    spec = ToolSpec(
        name="stop_channel",
        purpose="Stop watching a calendar resource through a push channel.",
        input_model=StopChannelInput,
        output_model=StatusOutput,
        permissions=_CALENDAR_READ,
        side_effects=True,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        requires_approval=True,
        approval_action="calendar.channel_stop",
        risk=ToolRisk.MEDIUM,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, StopChannelInput)
        from nexapilot.services.calendar_service import calendar_client

        _, client = calendar_client(ctx, args.account_id)
        await client.stop_channel(args.channel_id, args.resource_id)
        return StatusOutput(status="stopped")


def _list_output(data: dict[str, Any]) -> CalendarListOutput:
    items = [item for item in data.get("items") or [] if isinstance(item, dict)]
    return CalendarListOutput(
        items=items,
        count=len(items),
        next_page_token=str(data.get("nextPageToken") or ""),
        next_sync_token=str(data.get("nextSyncToken") or ""),
        data=data,
    )
