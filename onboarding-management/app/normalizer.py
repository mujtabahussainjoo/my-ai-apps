"""Normalize incoming events into the one canonical employee model.

Rules:
* Map source-specific field names (``name``, ``location``, ...) onto the
  canonical names in :class:`app.models.Field`.
* Trim/collapse whitespace, lowercase emails, canonicalize dates to
  ``YYYY-MM-DD`` and map *known* location synonyms.
* Never invent data: an unparseable date or unknown location is passed
  through unchanged so the validator can flag it. We do not guess.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.models import ALL_FIELDS, Field, RawEvent, StandardEmployee

# Source-specific key -> canonical field name.
FIELD_ALIASES: dict[str, str] = {
    "employee_id": Field.EMPLOYEE_ID,
    "id": Field.EMPLOYEE_ID,
    "emp_id": Field.EMPLOYEE_ID,
    "name": Field.LEGAL_NAME,
    "full_name": Field.LEGAL_NAME,
    "legal_name": Field.LEGAL_NAME,
    "preferred_name": Field.PREFERRED_NAME,
    "preferredname": Field.PREFERRED_NAME,
    "nickname": Field.PREFERRED_NAME,
    "start_date": Field.START_DATE,
    "startdate": Field.START_DATE,
    "start": Field.START_DATE,
    "location": Field.WORK_LOCATION,
    "work_location": Field.WORK_LOCATION,
    "worklocation": Field.WORK_LOCATION,
    "office": Field.WORK_LOCATION,
    "address": Field.SHIPPING_ADDRESS,
    "shipping_address": Field.SHIPPING_ADDRESS,
    "shippingaddress": Field.SHIPPING_ADDRESS,
    "department": Field.DEPARTMENT,
    "dept": Field.DEPARTMENT,
    "team": Field.DEPARTMENT,
    "job_title": Field.JOB_TITLE,
    "jobtitle": Field.JOB_TITLE,
    "title": Field.JOB_TITLE,
    "role": Field.JOB_TITLE,
    "personal_email": Field.PERSONAL_EMAIL,
    "personalemail": Field.PERSONAL_EMAIL,
    "email": Field.PERSONAL_EMAIL,
    "manager": Field.MANAGER,
    "manager_name": Field.MANAGER,
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%dT%H:%M:%S",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
)

# Known synonyms only. Unknown values are left untouched (validator flags them).
LOCATION_ALIASES: dict[str, str] = {
    "blr": "Bangalore",
    "bengaluru": "Bangalore",
    "bangalore": "Bangalore",
    "hyd": "Hyderabad",
    "hyderabad": "Hyderabad",
    "ggn": "Gurgaon",
    "gurugram": "Gurgaon",
    "gurgaon": "Gurgaon",
    "bom": "Mumbai",
    "mumbai": "Mumbai",
    "pune": "Pune",
    "london": "London",
    "remote": "Remote",
}

_WS_RE = re.compile(r"\s+")


def _clean(value: object) -> str:
    if value is None:
        return ""
    return _WS_RE.sub(" ", str(value)).strip()


def normalize_date(value: object) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw  # unparseable -> pass through for the validator


def normalize_location(value: object) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    return LOCATION_ALIASES.get(raw.lower(), raw)


def normalize_email(value: object) -> str:
    return _clean(value).lower()


def normalize_changed_fields(fields: list[str]) -> list[str]:
    """Map a source's changed-field names onto canonical names."""
    result: list[str] = []
    for name in fields:
        canonical = FIELD_ALIASES.get(str(name).lower())
        if canonical and canonical not in result:
            result.append(canonical)
    return result


def normalize_employee(event: RawEvent) -> StandardEmployee:
    """Convert a raw source event into the canonical employee model."""
    raw = event.employee or {}
    canonical: dict[str, object] = {}

    for key, value in raw.items():
        target = FIELD_ALIASES.get(str(key).lower())
        if target and target not in canonical:
            canonical[target] = value

    # The event envelope's employee_id is authoritative for identity.
    if event.employee_id:
        canonical[Field.EMPLOYEE_ID] = event.employee_id

    normalized: dict[str, str] = {}
    for name in ALL_FIELDS:
        value = canonical.get(name, "")
        if name == Field.START_DATE:
            normalized[name] = normalize_date(value)
        elif name == Field.WORK_LOCATION:
            normalized[name] = normalize_location(value)
        elif name in (Field.PERSONAL_EMAIL,):
            normalized[name] = normalize_email(value)
        else:
            normalized[name] = _clean(value)

    return StandardEmployee.from_dict(normalized)
