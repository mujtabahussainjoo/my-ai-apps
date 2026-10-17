"""Repository package.

Each repository translates ORM rows to typed schemas and never leaks ORM objects. Import
the concrete repositories from here.
"""

from __future__ import annotations

from ecommerce_support.db.repositories.audit import AuditEventRepository
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.db.repositories.conversation import ConversationRepository
from ecommerce_support.db.repositories.document import DocumentRepository
from ecommerce_support.db.repositories.eval_result import EvalResultRepository
from ecommerce_support.db.repositories.feedback import FeedbackRepository
from ecommerce_support.db.repositories.order import OrderRepository
from ecommerce_support.db.repositories.product import ProductRepository
from ecommerce_support.db.repositories.ticket import TicketRepository
from ecommerce_support.db.repositories.tool_execution import ToolExecutionRepository
from ecommerce_support.db.repositories.user import UserRepository

__all__ = [
    "AuditEventRepository",
    "BaseRepository",
    "ConversationRepository",
    "DocumentRepository",
    "EvalResultRepository",
    "FeedbackRepository",
    "OrderRepository",
    "ProductRepository",
    "TicketRepository",
    "ToolExecutionRepository",
    "UserRepository",
]
