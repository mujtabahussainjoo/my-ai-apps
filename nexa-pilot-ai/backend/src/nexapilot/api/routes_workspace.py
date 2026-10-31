"""Calendar, finance and coding workspace routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nexapilot.api.deps import ContainerDep, SessionDep
from nexapilot.core.container import Container
from nexapilot.core.errors import ExternalServiceNotConfiguredError
from nexapilot.tools.base import ToolContext

router = APIRouter(prefix="/api", tags=["workspace"])


class FreebusyRequest(BaseModel):
    time_min: str = Field(min_length=10, max_length=64)
    time_max: str = Field(min_length=10, max_length=64)
    timezone: str = Field(default="UTC", max_length=80)
    items: list[str] = Field(default_factory=list, max_length=100)


def _calendar_ctx(container: Container, session: Session) -> ToolContext:
    return ToolContext(container=container, session=session)


@router.get("/calendar/calendar-list")
async def list_calendar_list(
    account_id: str = "",
    max_results: int = 250,
    page_token: str = "",
    min_access_role: str = "",
    show_deleted: bool = False,
    show_hidden: bool = False,
    sync_token: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    return await client.list_calendar_list(
        max_results=min(max_results, 250),
        page_token=page_token,
        min_access_role=min_access_role,
        show_deleted=show_deleted,
        show_hidden=show_hidden,
        sync_token=sync_token,
    )


@router.get("/calendar/calendar-list/{calendar_id}")
async def get_calendar_list_entry(
    calendar_id: str,
    account_id: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    return await client.get_calendar_list_entry(calendar_id)


@router.get("/calendar/calendars/{calendar_id}")
async def get_calendar(
    calendar_id: str,
    account_id: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    return await client.get_calendar(calendar_id)


@router.get("/calendar/colors")
async def get_calendar_colors(
    account_id: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    return await client.get_colors()


@router.get("/calendar/settings")
async def list_calendar_settings(
    account_id: str = "",
    max_results: int = 250,
    page_token: str = "",
    sync_token: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    return await client.list_settings(
        max_results=min(max_results, 250),
        page_token=page_token,
        sync_token=sync_token,
    )


@router.get("/calendar/settings/{setting}")
async def get_calendar_setting(
    setting: str,
    account_id: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    return await client.get_setting(setting)


@router.get("/calendar/acl")
async def list_calendar_acl(
    calendar_id: str = "primary",
    account_id: str = "",
    max_results: int = 100,
    page_token: str = "",
    show_deleted: bool = False,
    sync_token: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    return await client.list_acl(
        calendar_id=calendar_id,
        max_results=min(max_results, 100),
        page_token=page_token,
        show_deleted=show_deleted,
        sync_token=sync_token,
    )


@router.post("/calendar/freebusy")
async def query_calendar_freebusy(
    payload: FreebusyRequest,
    account_id: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    items = [{"id": item} for item in payload.items] or [{"id": "primary"}]
    return await client.query_freebusy(
        {
            "timeMin": payload.time_min,
            "timeMax": payload.time_max,
            "timeZone": payload.timezone,
            "items": items,
        }
    )


@router.get("/calendar/events/{event_id}")
async def get_calendar_event(
    event_id: str,
    calendar_id: str = "primary",
    account_id: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    client.calendar_id = calendar_id
    event = await client.get_event(event_id)
    return event.to_dict()


@router.get("/calendar/events/{event_id}/instances")
async def list_calendar_event_instances(
    event_id: str,
    calendar_id: str = "primary",
    account_id: str = "",
    limit: int = 250,
    page_token: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.calendar_service import calendar_client

    _, client = calendar_client(_calendar_ctx(container, session), account_id)
    client.calendar_id = calendar_id
    events, next_page = await client.list_event_instances(
        event_id, max_results=min(limit, 2500), page_token=page_token
    )
    return {
        "items": [event.to_dict() for event in events],
        "next_page_token": next_page,
    }


@router.get("/calendar/events")
def list_calendar_events(
    start: str = "",
    end: str = "",
    limit: int = 100,
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> list[dict[str, Any]]:
    from nexapilot.services.calendar_service import list_events

    ctx = ToolContext(container=container, session=session)
    return list_events(
        ctx,
        start=_parse_dt(start) if start else None,
        end=_parse_dt(end) if end else None,
        limit=min(limit, 500),
    )


@router.post("/calendar/sync")
async def sync_calendar(
    account_id: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.db.models import ConnectedAccount
    from nexapilot.services.calendar_service import extract_events_from_emails, sync_calendar
    from nexapilot.tools.base import ToolContext

    ctx = ToolContext(container=container, session=session)
    accounts = list(
        session.query(ConnectedAccount).filter(ConnectedAccount.status == "connected").all()
    )
    if account_id:
        accounts = [account for account in accounts if account.id == account_id]
    if not accounts:
        raise ExternalServiceNotConfiguredError(
            "No calendar account is connected.",
            setup_hint="Connect a Google account in Settings → Connected accounts.",
        )
    results: list[dict[str, Any]] = []
    for account in accounts:
        try:
            results.append(await sync_calendar(ctx, account))
        except ExternalServiceNotConfiguredError as exc:
            results.append({"account_id": account.id, "skipped": exc.message})
    extracted = await extract_events_from_emails(ctx, account_id)
    session.commit()
    return {"calendars": results, "email_events": extracted}


@router.get("/finance/portfolio")
async def get_portfolio(
    portfolio_id: str = "",
    container: Container = ContainerDep,
    session: Session = SessionDep,
) -> dict[str, Any]:
    from nexapilot.services.finance_service import portfolio_summary
    from nexapilot.tools.base import ToolContext

    ctx = ToolContext(container=container, session=session)
    return await portfolio_summary(ctx, portfolio_id)


@router.get("/finance/orders")
def list_orders(
    portfolio_id: str = "", container: Container = ContainerDep, session: Session = SessionDep
) -> list[dict[str, Any]]:
    from nexapilot.services.finance_service import list_orders as _list
    from nexapilot.tools.base import ToolContext

    ctx = ToolContext(container=container, session=session)
    return _list(ctx, portfolio_id)


@router.get("/finance/watchlist")
def get_watchlist(
    container: Container = ContainerDep, session: Session = SessionDep
) -> list[dict[str, Any]]:
    from nexapilot.services.finance_service import watchlist
    from nexapilot.tools.base import ToolContext

    ctx = ToolContext(container=container, session=session)
    return watchlist(ctx)


@router.get("/coding/files")
def list_coding_files(path: str = ".", container: Container = ContainerDep) -> dict[str, Any]:
    from nexapilot.integrations import sandbox

    root = container.settings.coding_workspace_root
    if not root:
        raise ExternalServiceNotConfiguredError(
            "No coding workspace is configured.",
            setup_hint="Set a workspace folder in Settings → Coding.",
        )
    workspace = sandbox.resolve_workspace(root)
    files = sandbox.list_files(workspace, path)
    return {"root": str(workspace), "files": files}


def _parse_dt(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _default_window() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    return now, now + timedelta(days=7)
