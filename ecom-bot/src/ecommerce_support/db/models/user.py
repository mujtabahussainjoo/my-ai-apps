"""Identity references for authenticated customers (DATA-001 ``users``)."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ecommerce_support.db.base import Base
from ecommerce_support.db.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """A customer identity reference. Owns conversations, orders, and feedback."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
