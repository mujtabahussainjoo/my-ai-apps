"""ORM models.

Repositories translate between these objects and API payloads; ORM instances are
never returned directly to the API layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderConfig(Base, TimestampMixin):
    """A saved provider configuration. Exactly one row may have ``is_active`` true."""

    __tablename__ = "provider_config"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    auth_mode: Mapped[str] = mapped_column(String(64), default="api_key")
    secret_reference: Mapped[str] = mapped_column(String(200), default="")
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SecretReference(Base, TimestampMixin):
    """Index of secret references stored in the OS vault (never the values)."""

    __tablename__ = "secret_reference"

    reference: Mapped[str] = mapped_column(String(200), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), default="")
    label: Mapped[str] = mapped_column(String(200), default="")
    account_id: Mapped[str] = mapped_column(String(64), default="")


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), default="New conversation")
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(200), default="")


class Message(Base):
    __tablename__ = "message"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskRun(Base, TimestampMixin):
    """One execution of an agent workflow."""

    __tablename__ = "task_run"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    workflow: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    steps: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRequest(Base, TimestampMixin):
    """An action that requires explicit user approval before it may execute."""

    __tablename__ = "approval_request"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    task_run_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    target: Mapped[str] = mapped_column(String(300), default="")
    provider: Mapped[str] = mapped_column(String(64), default="")
    risk: Mapped[str] = mapped_column(String(32), default="low")
    cost: Mapped[str] = mapped_column(String(120), default="")
    consequences: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")


class ConnectedAccount(Base, TimestampMixin):
    """An authorized email/calendar/travel/finance account."""

    __tablename__ = "connected_account"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(200), default="")
    label: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(300), default="")
    auth_mode: Mapped[str] = mapped_column(String(64), default="")
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="connected", index=True)
    sync_cursor: Mapped[str] = mapped_column(String(500), default="")
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class EmailMessage(Base):
    __tablename__ = "email_message"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("connected_account.id", ondelete="CASCADE"), index=True
    )
    provider_message_id: Mapped[str] = mapped_column(String(300), default="", index=True)
    thread_id: Mapped[str] = mapped_column(String(300), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    sender: Mapped[str] = mapped_column(String(300), default="")
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list)
    snippet: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    folder: Mapped[str] = mapped_column(String(120), default="INBOX")
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("account_id", "provider_message_id", name="uq_email_account_message"),
    )


class CalendarEvent(Base, TimestampMixin):
    __tablename__ = "calendar_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    source: Mapped[str] = mapped_column(String(32), default="calendar", index=True)
    external_id: Mapped[str] = mapped_column(String(300), default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="confirmed")
    provenance: Mapped[str] = mapped_column(String(200), default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    dedupe_key: Mapped[str] = mapped_column(String(300), default="", index=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("account_id", "source", "dedupe_key", name="uq_event_dedupe"),
    )


class Portfolio(Base, TimestampMixin):
    __tablename__ = "portfolio"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), default="My portfolio")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)


class Position(Base, TimestampMixin):
    __tablename__ = "position"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolio.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(24), default="stock")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    average_cost: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (UniqueConstraint("portfolio_id", "symbol", name="uq_position_symbol"),)


class Order(Base, TimestampMixin):
    __tablename__ = "order"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    portfolio_id: Mapped[str] = mapped_column(
        ForeignKey("portfolio.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(24), default="stock")
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), default="market")
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    filled_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), default="paper")
    provider_reference: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(Text, default="")


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_item"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(24), default="stock")
    note: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (UniqueConstraint("symbol", "asset_type", name="uq_watchlist_symbol"),)


class AuditLog(Base):
    """Append-only audit trail. Records actions, not sensitive payloads."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    actor: Mapped[str] = mapped_column(String(64), default="user")
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(32), default="ok")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
