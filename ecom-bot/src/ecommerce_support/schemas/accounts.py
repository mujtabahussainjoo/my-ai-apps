"""Account/identity contracts (FR-023). Never carries credentials or secrets."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from ecommerce_support.schemas.common import Schema

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserProfile(Schema):
    """An authenticated customer's own profile. Contains no secrets."""

    user_id: str = Field(min_length=1)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)
    created_at: datetime | None = None

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.lower()


class AccountSummary(Schema):
    """Account overview returned to the owning customer only."""

    user_id: str = Field(min_length=1)
    display_name: str | None = Field(default=None, max_length=200)
    order_count: int = Field(default=0, ge=0)
    member_since: datetime | None = None
