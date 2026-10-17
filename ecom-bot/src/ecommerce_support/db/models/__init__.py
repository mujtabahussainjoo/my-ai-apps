"""ORM models for all DATA-001 tables.

Importing this package registers every model on ``Base.metadata`` so Alembic
autogenerate sees the complete schema.
"""

from __future__ import annotations

from ecommerce_support.db.models.audit import AuditEvent
from ecommerce_support.db.models.conversation import Conversation, Message
from ecommerce_support.db.models.document import EMBEDDING_DIMENSIONS, DocumentChunk, PolicyDocument
from ecommerce_support.db.models.eval_result import EvalResult
from ecommerce_support.db.models.feedback import Feedback
from ecommerce_support.db.models.order import Order, OrderItem
from ecommerce_support.db.models.product import Product
from ecommerce_support.db.models.ticket import SupportTicket
from ecommerce_support.db.models.tool_execution import ToolExecution
from ecommerce_support.db.models.user import User

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "AuditEvent",
    "Conversation",
    "DocumentChunk",
    "EvalResult",
    "Feedback",
    "Message",
    "Order",
    "OrderItem",
    "PolicyDocument",
    "Product",
    "SupportTicket",
    "ToolExecution",
    "User",
]
