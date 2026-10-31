"""Research tools: web search and source verification."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nexapilot.agents.permissions import WEB_SEARCH
from nexapilot.integrations.fetch import PageContent, fetch_page
from nexapilot.integrations.search import SearchResult, build_search_provider
from nexapilot.tools.base import Tool, ToolContext, ToolRisk, ToolSpec

SEARCH_SECRET_REFERENCE = "search:{provider}:api_key"


class WebSearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    count: int = Field(default=5, ge=1, le=20)


class WebSearchOutput(BaseModel):
    query: str
    provider: str
    results: list[dict[str, Any]] = Field(default_factory=list)
    searched_at: str


class FetchPageInput(BaseModel):
    url: str = Field(min_length=8, max_length=1000)


class FetchPageOutput(BaseModel):
    url: str
    title: str = ""
    text: str = ""
    fetched_at: str
    status: int = 200
    truncated: bool = False


class WebSearchTool(Tool):
    spec = ToolSpec(
        name="web_search",
        purpose="Search the web for current information and return source links.",
        input_model=WebSearchInput,
        output_model=WebSearchOutput,
        permissions=frozenset({WEB_SEARCH}),
        side_effects=False,
        timeout_seconds=45.0,
        max_retries=1,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, WebSearchInput)
        settings = ctx.container.settings
        provider = build_search_provider(
            settings.web_search_provider,
            api_key=ctx.container.secrets.get(
                SEARCH_SECRET_REFERENCE.format(provider=settings.web_search_provider)
            )
            or "",
            endpoint=settings.web_search_endpoint,
        )
        results: list[SearchResult] = await provider.search(args.query, count=args.count)
        return WebSearchOutput(
            query=args.query,
            provider=provider.id,
            results=[result.to_dict() for result in results],
            searched_at=_now_iso(),
        )


class FetchPageTool(Tool):
    spec = ToolSpec(
        name="fetch_page",
        purpose="Open a web page and return its readable text to verify a claim.",
        input_model=FetchPageInput,
        output_model=FetchPageOutput,
        permissions=frozenset({WEB_SEARCH}),
        side_effects=False,
        timeout_seconds=45.0,
        max_retries=1,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, FetchPageInput)
        page: PageContent = await fetch_page(args.url)
        return FetchPageOutput(
            url=page.url,
            title=page.title,
            text=page.text,
            fetched_at=page.fetched_at.isoformat(),
            status=page.status,
            truncated=page.truncated,
        )


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
