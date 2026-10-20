"""Shared domain enumerations used across API, agent, tool, and DB contracts.

String values are stable wire/DB identifiers; do not rename without a migration and a
contract update. Conversation lifecycle values match `requirement.md` FR-047 exactly.
"""

from __future__ import annotations

from enum import StrEnum


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ConversationStatus(StrEnum):
    """Conversation lifecycle states (FR-047)."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER"
    RESOLVED = "RESOLVED"
    ESCALATION_PENDING = "ESCALATION_PENDING"
    TICKET_CREATED = "TICKET_CREATED"
    TICKET_CREATION_FAILED = "TICKET_CREATION_FAILED"
    ABANDONED = "ABANDONED"
    ERROR = "ERROR"


class ResolutionOutcome(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    ESCALATED = "escalated"
    ABANDONED = "abandoned"


class ResolutionAction(StrEnum):
    """What the Resolution Agent decides after an answer (FR-024)."""

    AWAIT_CUSTOMER = "await_customer"
    RETRY = "retry"
    ESCALATE = "escalate"
    RESOLVED = "resolved"


class Confirmation(StrEnum):
    """The customer's answer to the "did that resolve your issue?" prompt (FR-046)."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class Intent(StrEnum):
    ORDER = "order"
    PRODUCT = "product"
    POLICY = "policy"
    ACCOUNT = "account"
    FEEDBACK = "feedback"
    ESCALATION = "escalation"
    GENERAL = "general"
    CLARIFY = "clarify"


class AgentName(StrEnum):
    SUPERAGENT = "superagent"
    ORDER = "order"
    PRODUCT = "product"
    POLICY = "policy"
    ACCOUNT = "account"
    RESOLUTION = "resolution"
    ESCALATION = "escalation"
    FEEDBACK = "feedback"
    GENERAL = "general"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELAYED = "delayed"
    FAILED_DELIVERY = "failed_delivery"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    REFUNDED = "refunded"


class StockStatus(StrEnum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    BACKORDER = "backorder"


class TicketProvider(StrEnum):
    MOCK = "mock"
    JIRA = "jira"
    SERVICENOW = "servicenow"


class TicketStatus(StrEnum):
    PENDING = "pending"
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    FAILED = "failed"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ToolCallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
