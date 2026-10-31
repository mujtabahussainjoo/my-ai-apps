"""Permission model.

Permissions are granted by configuration and by connected accounts, and they are
enforced in code by the tool layer — never by prompt wording.
"""

from __future__ import annotations

from dataclasses import dataclass

# Permission names -------------------------------------------------------------
EMAIL_READ = "email:read"
EMAIL_SEND = "email:send"
EMAIL_MODIFY = "email:modify"
CALENDAR_READ = "calendar:read"
CALENDAR_WRITE = "calendar:write"
TRAVEL_SEARCH = "travel:search"
TRAVEL_BOOK = "travel:book"
FINANCE_READ = "finance:read"
FINANCE_TRADE = "finance:trade"
WEB_SEARCH = "web:search"
FS_READ = "fs:read"
FS_WRITE = "fs:write"
SHELL_EXEC = "shell:exec"
SHELL_ADMIN = "shell:admin"


@dataclass(frozen=True)
class WorkflowPermissions:
    workflow: str
    permissions: frozenset[str]
    tools: tuple[str, ...]


WORKFLOW_PERMISSIONS: dict[str, WorkflowPermissions] = {
    "general": WorkflowPermissions("general", frozenset({}), ()),
    "research": WorkflowPermissions(
        "research",
        frozenset({WEB_SEARCH}),
        ("web_search", "fetch_page"),
    ),
    "travel": WorkflowPermissions(
        "travel",
        frozenset({TRAVEL_SEARCH}),
        ("search_flights", "search_hotels", "search_trains"),
    ),
    "email": WorkflowPermissions(
        "email",
        frozenset({EMAIL_READ, EMAIL_SEND, EMAIL_MODIFY}),
        (
            "search_email",
            "read_email",
            "create_draft",
            "send_email",
            "forward_email",
            "delete_email",
        ),
    ),
    "calendar": WorkflowPermissions(
        "calendar",
        frozenset({CALENDAR_READ, CALENDAR_WRITE}),
        (
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
        ),
    ),
    "finance": WorkflowPermissions(
        "finance",
        frozenset({FINANCE_READ, FINANCE_TRADE}),
        ("quote_symbol", "portfolio_summary", "watchlist", "place_order"),
    ),
    "coding": WorkflowPermissions(
        "coding",
        frozenset({FS_READ, FS_WRITE, SHELL_EXEC}),
        ("read_file", "write_file", "list_files", "run_tests", "diff"),
    ),
}


def permissions_for_workflow(workflow: str) -> frozenset[str]:
    entry = WORKFLOW_PERMISSIONS.get(workflow)
    return entry.permissions if entry else frozenset()


def tools_for_workflow(workflow: str) -> tuple[str, ...]:
    entry = WORKFLOW_PERMISSIONS.get(workflow)
    return entry.tools if entry else ()
