"""Web search providers.

Three interchangeable backends are supported: Brave Search, Tavily and a
self-hosted SearxNG instance. If no backend is configured the research agent
must say so — it must never pretend to search.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from nexapilot.core.errors import ExternalServiceNotConfiguredError, IntegrationError
from nexapilot.core.logging import get_logger
from nexapilot.providers.http import classify_status, wrap_transport_error

log = get_logger(__name__)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    published_at: datetime | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "source": self.source,
        }


class SearchProvider(abc.ABC):
    id: str = "search"

    @abc.abstractmethod
    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]: ...


class BraveSearchProvider(SearchProvider):
    id = "brave"

    def __init__(self, api_key: str, *, timeout: float = 30.0, transport: Any = None) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]:
        if not self._api_key:
            raise ExternalServiceNotConfiguredError(
                "Brave Search is selected but no API key is stored.",
                setup_hint="Add a Brave Search API key in Settings → Search.",
            )
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._api_key,
        }
        params = {"q": query, "count": str(count)}
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.get(url, headers=headers, params=params)
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "Brave Search", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "Brave Search", response.text)
            data = response.json()

        results: list[SearchResult] = []
        for item in (data.get("web") or {}).get("results", [])[:count]:
            if not isinstance(item, dict):
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("description") or ""),
                    published_at=_parse_date(item.get("age") or item.get("page_age")),
                    source=self.id,
                )
            )
        return results


class TavilySearchProvider(SearchProvider):
    id = "tavily"

    def __init__(self, api_key: str, *, timeout: float = 30.0, transport: Any = None) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]:
        if not self._api_key:
            raise ExternalServiceNotConfiguredError(
                "Tavily is selected but no API key is stored.",
                setup_hint="Add a Tavily API key in Settings → Search.",
            )
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": count,
            "search_depth": "basic",
            "include_answer": False,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "Tavily", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "Tavily", response.text)
            data = response.json()

        results: list[SearchResult] = []
        for item in data.get("results", [])[:count]:
            if not isinstance(item, dict):
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("content") or ""),
                    published_at=_parse_date(item.get("published_date")),
                    source=self.id,
                )
            )
        return results


class SearxngSearchProvider(SearchProvider):
    id = "searxng"

    def __init__(self, base_url: str, *, timeout: float = 30.0, transport: Any = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    async def search(self, query: str, *, count: int = 5) -> list[SearchResult]:
        if not self._base_url:
            raise ExternalServiceNotConfiguredError(
                "SearxNG is selected but no instance URL is configured.",
                setup_hint="Set the SearxNG instance URL in Settings → Search.",
            )
        url = f"{self._base_url}/search"
        params = {"q": query, "format": "json", "language": "en"}
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "SearxNG", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "SearxNG", response.text)
            data = response.json()

        results: list[SearchResult] = []
        for item in data.get("results", [])[:count]:
            if not isinstance(item, dict):
                continue
            published = item.get("publishedDate")
            results.append(
                SearchResult(
                    title=str(item.get("title") or ""),
                    url=str(item.get("url") or ""),
                    snippet=str(item.get("content") or ""),
                    published_at=_parse_date(published),
                    source=self.id,
                )
            )
        return results


def _parse_date(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def build_search_provider(
    provider: str,
    *,
    api_key: str = "",
    endpoint: str = "",
    timeout: float = 30.0,
    transport: Any = None,
) -> SearchProvider:
    """Instantiate the configured search provider.

    Raises :class:`ExternalServiceNotConfiguredError` when nothing is configured —
    the caller must then tell the user how to set it up.
    """
    if provider == "brave":
        return BraveSearchProvider(api_key, timeout=timeout, transport=transport)
    if provider == "tavily":
        return TavilySearchProvider(api_key, timeout=timeout, transport=transport)
    if provider == "searxng":
        if not endpoint:
            raise ExternalServiceNotConfiguredError(
                "SearxNG is selected but no instance URL is configured.",
                setup_hint="Set the SearxNG instance URL in Settings → Search.",
            )
        return SearxngSearchProvider(endpoint, timeout=timeout, transport=transport)
    raise ExternalServiceNotConfiguredError(
        "No web search provider is configured, so live web search is unavailable.",
        setup_hint=(
            "Configure Brave Search, Tavily or a SearxNG instance in Settings → Search. "
            "Until then NexaPilot cannot retrieve live web results."
        ),
    )


def search_provider_configured(provider: str, *, api_key: str = "", endpoint: str = "") -> bool:
    if provider == "brave" or provider == "tavily":
        return bool(api_key)
    if provider == "searxng":
        return bool(endpoint)
    return False


__all__ = [
    "BraveSearchProvider",
    "ExternalServiceNotConfiguredError",
    "IntegrationError",
    "SearchProvider",
    "SearchResult",
    "SearxngSearchProvider",
    "TavilySearchProvider",
    "build_search_provider",
    "search_provider_configured",
]
