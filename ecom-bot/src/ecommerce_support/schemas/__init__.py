"""Pydantic v2 contracts shared by API, agents, tools, RAG, and services.

Contracts are the stable boundary between layers: request/response schemas, agent/worker
I/O, commerce entities, feedback, ticketing, and RAG models. Persistence mapping lives in
``db/`` — ORM objects never cross into these contracts.

Import from the package root for convenience (``from ecommerce_support.schemas import
ChatRequest``) or from the specific module.
"""

from __future__ import annotations

from ecommerce_support.schemas.accounts import AccountSummary, UserProfile
from ecommerce_support.schemas.agents import (
    AgentResponse,
    AgentState,
    RoutingDecision,
    SourceCitation,
    ToolCallRequest,
    ToolExecution,
)
from ecommerce_support.schemas.audit import AuditEvent, AuditEventCreate
from ecommerce_support.schemas.chat import (
    MAX_CONTENT_CHARS,
    MAX_MESSAGE_CHARS,
    ChatRequest,
    ChatResponse,
    Conversation,
    ConversationSummary,
    Message,
    MessageCreate,
)
from ecommerce_support.schemas.common import (
    CURRENCY_PATTERN,
    ErrorDetail,
    ErrorResponse,
    ORMReadableSchema,
    Page,
    PageParams,
    Schema,
)
from ecommerce_support.schemas.documents import (
    DocumentChunk,
    PolicyDocument,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)
from ecommerce_support.schemas.enums import (
    AgentName,
    ConversationStatus,
    DocumentStatus,
    Intent,
    MessageRole,
    OrderStatus,
    Priority,
    ResolutionOutcome,
    StockStatus,
    TicketProvider,
    TicketStatus,
    ToolCallStatus,
)
from ecommerce_support.schemas.eval import EvalResult, EvalResultCreate
from ecommerce_support.schemas.feedback import Feedback, FeedbackRequest
from ecommerce_support.schemas.orders import (
    Address,
    Order,
    OrderItem,
    OrderSummary,
    ReturnEligibility,
    Shipment,
    ShipmentEvent,
)
from ecommerce_support.schemas.products import (
    Product,
    ProductSearchQuery,
    ProductSummary,
    StockInfo,
)
from ecommerce_support.schemas.tickets import Ticket, TicketRequest, TicketStatusResponse

__all__ = [
    "CURRENCY_PATTERN",
    "MAX_CONTENT_CHARS",
    "MAX_MESSAGE_CHARS",
    "AccountSummary",
    "Address",
    "AgentName",
    "AgentResponse",
    "AgentState",
    "AuditEvent",
    "AuditEventCreate",
    "ChatRequest",
    "ChatResponse",
    "Conversation",
    "ConversationStatus",
    "ConversationSummary",
    "DocumentChunk",
    "DocumentStatus",
    "ErrorDetail",
    "ErrorResponse",
    "EvalResult",
    "EvalResultCreate",
    "Feedback",
    "FeedbackRequest",
    "Intent",
    "Message",
    "MessageCreate",
    "MessageRole",
    "ORMReadableSchema",
    "Order",
    "OrderItem",
    "OrderStatus",
    "OrderSummary",
    "Page",
    "PageParams",
    "PolicyDocument",
    "Priority",
    "Product",
    "ProductSearchQuery",
    "ProductSummary",
    "ResolutionOutcome",
    "RetrievalHit",
    "RetrievalQuery",
    "RetrievalResult",
    "ReturnEligibility",
    "RoutingDecision",
    "Schema",
    "Shipment",
    "ShipmentEvent",
    "SourceCitation",
    "StockInfo",
    "StockStatus",
    "Ticket",
    "TicketProvider",
    "TicketRequest",
    "TicketStatus",
    "TicketStatusResponse",
    "ToolCallRequest",
    "ToolCallStatus",
    "ToolExecution",
    "UserProfile",
]
