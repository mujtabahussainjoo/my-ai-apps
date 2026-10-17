"""Configured RSS/Atom news sources, bounded and timestamped before AI review."""

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx
from pydantic import Field

from src.core.security import sanitize_untrusted
from src.schemas.base import Base


class NewsItem(Base):
    title: str = Field(min_length=1, max_length=500)
    source: str
    url: str
    published_at: datetime


def parse_feed(body: bytes, source: str, *, max_age_hours=24, now=None):
    if len(body) > 1_048_576 or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Unsafe or oversized news feed")
    root = ElementTree.fromstring(body)
    now = now or datetime.now(UTC)
    items = []
    for node in list(root.findall(".//item")) + list(root.findall("{http://www.w3.org/2005/Atom}entry")):

        def value(name, node=node):
            return node.findtext(name) or node.findtext("{http://www.w3.org/2005/Atom}" + name)

        date = value("pubDate") or value("published") or value("updated")
        if not date:
            continue
        try:
            published = (
                parsedate_to_datetime(date)
                if "," in date
                else datetime.fromisoformat(date.replace("Z", "+00:00"))
            )
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            if published > now or published < now - timedelta(hours=max_age_hours):
                continue
            title = sanitize_untrusted(value("title") or "", max_length=500, field="news title")
            link = value("link")
            if not link:
                element = node.find("{http://www.w3.org/2005/Atom}link")
                link = element.get("href", "") if element is not None else ""
            if not title:
                continue
            items.append(NewsItem(title=title, source=source, url=link or "", published_at=published))
        except (ValueError, TypeError):
            continue
    unique = {item.url or item.title: item for item in items}
    return sorted(unique.values(), key=lambda item: item.published_at, reverse=True)[:30]


class NewsCollector:
    def __init__(self, settings):
        self.settings = settings

    def fetch(self):
        items = []
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            for url in self.settings.news_feed_urls[:5]:
                if not url.startswith("https://"):
                    raise ValueError("News feeds require HTTPS")
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_048_576:
                            raise ValueError("News feed too large")
                items.extend(parse_feed(bytes(body), url, max_age_hours=self.settings.news_max_age_hours))
        return [item.model_dump(mode="json") for item in items[:30]]
