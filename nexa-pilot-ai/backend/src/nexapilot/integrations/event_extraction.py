"""Event extraction from email content.

Extracts interview, exam, appointment, travel and deadline details from message
text. Every extraction carries provenance (which message it came from) and a
confidence score so inferred events can be distinguished from real calendar
entries.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

EVENT_KINDS: dict[str, tuple[str, ...]] = {
    "interview": ("interview", "interview scheduled", "technical round", "hr round", "panel"),
    "exam": ("exam", "test", "assessment", "quiz", "examination", "mock test"),
    "appointment": ("appointment", "booked", "meeting scheduled", "slot", "consultation"),
    "travel": ("flight", "train", "ticket", "itinerary", "check-in", "boarding", "departure"),
    "deadline": ("deadline", "due by", "submit by", "expires on", "last date"),
}

KEYWORD_WEIGHTS: dict[str, float] = {
    "interview": 0.9,
    "exam": 0.85,
    "appointment": 0.75,
    "travel": 0.8,
    "deadline": 0.7,
}

_DATE_PATTERNS = (
    re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
)
_MONTH_NAME = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?\s*(\d{4})?\b",
    re.IGNORECASE,
)
_TEXT_DATE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\b")
_TIME = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
_MEETING_LINK = re.compile(r"https?://\S+(?:meet|zoom|teams|webex)\S*", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractedEvent:
    kind: str
    title: str
    start_at: datetime | None
    end_at: datetime | None
    confidence: float
    provenance: str
    source_message_id: str = ""
    details: dict[str, Any] | None = None

    @property
    def dedupe_key(self) -> str:
        base = f"{self.kind}|{self.title.lower().strip()}|{self.start_at.isoformat() if self.start_at else ''}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
            "confidence": round(self.confidence, 3),
            "provenance": self.provenance,
            "source_message_id": self.source_message_id,
            "details": self.details or {},
            "dedupe_key": self.dedupe_key,
        }


def detect_kind(text: str) -> tuple[str, float] | None:
    lowered = text.lower()
    best: tuple[str, float] | None = None
    for kind, keywords in EVENT_KINDS.items():
        for keyword in keywords:
            if keyword in lowered:
                weight = KEYWORD_WEIGHTS.get(kind, 0.6)
                if best is None or weight > best[1]:
                    best = (kind, weight)
                break
    return best


def parse_dates(text: str, *, reference: datetime | None = None) -> list[datetime]:
    """Extract candidate dates from free text."""
    reference = reference or datetime.now(UTC)
    found: list[datetime] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) == 3 and groups[0].isdigit() and len(groups[0]) == 4:
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
            else:
                day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
            try:
                found.append(datetime(year, month, day, tzinfo=UTC))
            except ValueError:
                continue
    for match in _MONTH_NAME.finditer(text):
        day = int(match.group(1))
        month_number = _month_number(match.group(2))
        year = int(match.group(3)) if match.group(3) else reference.year
        if month_number is not None:
            try:
                candidate = datetime(year, month_number, day, tzinfo=UTC)
            except ValueError:
                continue
            if not match.group(3) and candidate < reference - timedelta(days=60):
                candidate = candidate.replace(year=year + 1)
            found.append(candidate)
    for match in _TEXT_DATE.finditer(text):
        month_number = _month_number(match.group(1))
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else reference.year
        if month_number is not None:
            try:
                found.append(datetime(year, month_number, day, tzinfo=UTC))
            except ValueError:
                continue
    unique: list[datetime] = []
    for item in found:
        if item not in unique:
            unique.append(item)
    return unique


def parse_time(text: str) -> tuple[int, int] | None:
    match = _TIME.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()
    if hour > 23:
        return None
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return hour, minute


def extract_events(
    *,
    subject: str,
    body: str,
    source_message_id: str = "",
    sender: str = "",
    received_at: datetime | None = None,
    reference: datetime | None = None,
) -> list[ExtractedEvent]:
    """Extract candidate events from one email message."""
    text = f"{subject}\n\n{body}".strip()
    kind_info = detect_kind(text)
    if kind_info is None:
        return []
    kind, confidence = kind_info
    reference = reference or received_at or datetime.now(UTC)

    dates = parse_dates(text, reference=reference)
    times = parse_time(text)
    start: datetime | None = dates[0] if dates else None
    if start and times:
        start = start.replace(hour=times[0], minute=times[1])
    elif start:
        start = start.replace(hour=9, minute=0)

    end = start + timedelta(hours=1) if start else None
    if start and times:
        end = start + timedelta(hours=1)

    title = subject.strip() or f"{kind.title()} from {sender or 'email'}"
    details: dict[str, Any] = {}
    link = _MEETING_LINK.search(text)
    if link:
        details["meeting_link"] = link.group(0)
    if sender:
        details["sender"] = sender

    # Confidence drops when we have no date at all, since the event is vague.
    if start is None:
        confidence -= 0.25

    return [
        ExtractedEvent(
            kind=kind,
            title=title[:400],
            start_at=start,
            end_at=end,
            confidence=max(0.1, min(1.0, confidence)),
            provenance=f"email:{source_message_id or 'unknown'}",
            source_message_id=source_message_id,
            details=details,
        )
    ]


def _month_number(name: str) -> int | None:
    key = name.strip().lower()[:3]
    return MONTHS.get(key)


def parse_ics(text: str) -> list[dict[str, Any]]:
    """Parse an iCalendar payload into simple event dictionaries."""
    try:
        from icalendar import Calendar
    except ImportError:  # pragma: no cover - dependency is declared
        return []
    try:
        calendar = Calendar.from_ical(text)
    except (ValueError, TypeError):
        return []
    events: list[dict[str, Any]] = []
    for component in calendar.walk("VEVENT"):
        summary = str(component.get("summary") or "")
        start = component.get("dtstart")
        end = component.get("dtend")
        events.append(
            {
                "summary": summary,
                "uid": str(component.get("uid") or ""),
                "start": start.dt if start is not None else None,
                "end": end.dt if end is not None else None,
                "description": str(component.get("description") or ""),
                "location": str(component.get("location") or ""),
            }
        )
    return events
