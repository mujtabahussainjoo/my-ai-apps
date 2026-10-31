"""Safe web page fetching.

Used by the research agent to open and verify sources. Requests to private,
loopback and link-local addresses are refused so that a malicious page cannot
make the assistant probe the user's machine or internal network.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from nexapilot.core.errors import IntegrationError, PermissionDeniedError
from nexapilot.core.logging import get_logger

log = get_logger(__name__)

MAX_BYTES = 2_000_000
ALLOWED_SCHEMES = ("http", "https")

_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WHITESPACE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class PageContent:
    url: str
    title: str
    text: str
    fetched_at: datetime
    status: int = 200
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "fetched_at": self.fetched_at.isoformat(),
            "status": self.status,
            "truncated": self.truncated,
        }


def is_public_host(host: str) -> bool:
    """Return True when the host resolves only to public IP addresses."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise PermissionDeniedError(
            f"Only http(s) URLs can be fetched (got '{parsed.scheme or 'none'}')",
            details={"url": url[:200]},
        )
    if not parsed.hostname:
        raise PermissionDeniedError("URL has no host", details={"url": url[:200]})
    if not is_public_host(parsed.hostname):
        raise PermissionDeniedError(
            "Refusing to fetch a private or loopback address",
            details={"host": parsed.hostname},
        )
    return url


def html_to_text(markup: str) -> tuple[str, str]:
    """Extract a readable title and plain text from HTML."""
    title_match = _TITLE.search(markup)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""
    cleaned = _COMMENT.sub(" ", markup)
    cleaned = _SCRIPT_STYLE.sub(" ", cleaned)
    cleaned = _TAG.sub(" ", cleaned)
    text = html.unescape(cleaned)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = _WHITESPACE.sub("\n\n", text)
    return title, text


async def fetch_page(
    url: str,
    *,
    timeout: float = 30.0,
    max_bytes: int = MAX_BYTES,
    transport: Any = None,
) -> PageContent:
    """Fetch a page and return its readable text."""
    validate_url(url)
    async with httpx.AsyncClient(
        timeout=timeout,
        transport=transport,
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": "NexaPilotAI/0.1 (+desktop research agent)"},
    ) as client:
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            raise IntegrationError(
                f"Could not fetch page: {type(exc).__name__}", details={"url": url[:200]}
            ) from exc

        if response.status_code >= 400:
            raise IntegrationError(
                f"Source returned HTTP {response.status_code}",
                details={"url": url[:200], "status": response.status_code},
            )

        body = response.content[:max_bytes]
        truncated = len(response.content) > max_bytes
        content_type = response.headers.get("content-type", "")
        markup = body.decode(response.encoding or "utf-8", errors="replace")

    if "html" in content_type.lower() or markup.lstrip().startswith("<"):
        title, text = html_to_text(markup)
    else:
        title, text = "", markup.strip()

    return PageContent(
        url=str(response.url),
        title=title,
        text=text,
        fetched_at=datetime.now(UTC),
        status=response.status_code,
        truncated=truncated,
    )
