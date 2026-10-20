"""End-to-end fixtures: the real app stack wired to in-memory repositories.

These tests exercise the FR-critical paths (chat turn → agent graph → tools → persistence →
escalation/ticket → feedback) through the real services, graph, and integrations, with **mocks and
in-memory stores only** — no database, no credentials, and no outbound network (TASK-040).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from ecommerce_support.agents import EscalationAgent, create_agent_graph
from ecommerce_support.core.ids import new_id
from ecommerce_support.integrations import (
    InMemoryAccountAdapter,
    InMemoryCommerceAdapter,
    MockTicketingAdapter,
)
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.rag.generation import GroundedGenerator
from ecommerce_support.schemas import (
    AuditEvent,
    AuditEventCreate,
    Conversation,
    ConversationSummary,
    DocumentChunk,
    Feedback,
    FeedbackReport,
    FeedbackRequest,
    Message,
    RetrievalHit,
    RetrievalResult,
    Ticket,
    TicketRequest,
    UserProfile,
)
from ecommerce_support.schemas.agents import ToolExecution
from ecommerce_support.schemas.enums import (
    ConversationStatus,
    MessageRole,
    TicketProvider,
    TicketStatus,
)
from ecommerce_support.services import ChatService, TicketService
from ecommerce_support.services.conversations import ConversationService
from ecommerce_support.services.feedback import FeedbackService

_NOW = datetime(2026, 10, 19, tzinfo=UTC)


# --------------------------------------------------------------------------- in-memory stores


class InMemoryConversations:
    """Minimal in-memory stand-in for ``ConversationRepository`` (interface used by services)."""

    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}
        self.messages: dict[str, list[Message]] = {}

    async def create(
        self, *, user_id: str | None = None, tenant_id: str = "default"
    ) -> Conversation:
        conversation = Conversation(
            id=new_id("conv"),
            user_id=user_id,
            status=ConversationStatus.OPEN,
            created_at=_NOW,
            updated_at=_NOW,
        )
        self.conversations[conversation.id] = conversation
        self.messages[conversation.id] = []
        return conversation

    async def get(self, conversation_id: str) -> Conversation | None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            return None
        return conversation.model_copy(update={"messages": list(self.messages[conversation_id])})

    async def append_message(
        self,
        conversation_id: str,
        *,
        role: MessageRole,
        content: str,
        agent: Any = None,
    ) -> Message:
        message = Message(
            id=new_id("msg"),
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=_NOW,
            agent=agent,
        )
        self.messages[conversation_id].append(message)
        return message

    async def update_status(self, conversation_id: str, status: ConversationStatus) -> Conversation:
        conversation = self.conversations[conversation_id].model_copy(update={"status": status})
        self.conversations[conversation_id] = conversation
        return conversation

    async def list_messages(
        self, conversation_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[Message], int]:
        messages = self.messages.get(conversation_id, [])
        return messages[offset : offset + limit], len(messages)

    async def list_for_user(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[ConversationSummary], int]:
        owned = [c for c in self.conversations.values() if c.user_id == user_id]
        owned.sort(key=lambda c: c.created_at)
        summaries = [
            ConversationSummary(
                id=c.id,
                status=c.status,
                created_at=c.created_at,
                updated_at=c.updated_at,
                message_count=len(self.messages[c.id]),
            )
            for c in owned
        ]
        return summaries[offset : offset + limit], len(summaries)

    async def delete(self, conversation_id: str) -> bool:
        existed = self.conversations.pop(conversation_id, None) is not None
        self.messages.pop(conversation_id, None)
        return existed


class InMemoryToolExecutions:
    def __init__(self) -> None:
        self.rows: list[ToolExecution] = []
        self.by_message: dict[str, list[ToolExecution]] = {}

    async def record(
        self,
        *,
        conversation_id: str,
        message_id: str | None,
        tool_name: str,
        call_id: str,
        status: Any,
        summary: str = "",
        duration_ms: float | None = None,
    ) -> ToolExecution:
        execution = ToolExecution(
            call_id=call_id,
            tool_name=tool_name,
            status=status,
            summary=summary,
            duration_ms=duration_ms,
        )
        self.rows.append(execution)
        if message_id is not None:
            self.by_message.setdefault(message_id, []).append(execution)
        return execution

    async def list_by_message_ids(self, message_ids: list[str]) -> dict[str, list[ToolExecution]]:
        return {mid: self.by_message.get(mid, []) for mid in message_ids if mid in self.by_message}


class InMemoryTickets:
    def __init__(self) -> None:
        self.rows: dict[str, Ticket] = {}
        self.idempotency: dict[str, str] = {}

    async def get(self, ticket_id: str) -> Ticket | None:
        return self.rows.get(ticket_id)

    async def get_by_idempotency_key(self, idempotency_key: str) -> Ticket | None:
        ticket_id = self.idempotency.get(idempotency_key)
        return self.rows.get(ticket_id) if ticket_id is not None else None

    async def list_by_conversation(self, conversation_id: str) -> list[Ticket]:
        return [t for t in self.rows.values() if t.conversation_id == conversation_id]

    async def find_active_by_conversation(self, conversation_id: str) -> Ticket | None:
        for ticket in self.rows.values():
            if (
                ticket.conversation_id == conversation_id
                and ticket.status is not TicketStatus.FAILED
            ):
                return ticket
        return None

    async def create_failed(
        self, request: TicketRequest, *, provider: TicketProvider, error_code: str
    ) -> Ticket:
        ticket = Ticket(
            id=new_id("tkt"),
            conversation_id=request.conversation_id,
            provider=provider,
            status=TicketStatus.FAILED,
            summary=request.summary,
            priority=request.priority,
            created_at=_NOW,
        )
        self.rows[ticket.id] = ticket
        return ticket

    async def create_idempotent(
        self,
        request: TicketRequest,
        *,
        provider: TicketProvider,
        status: TicketStatus,
        external_id: str | None = None,
        url: str | None = None,
    ) -> tuple[Ticket, bool]:
        if request.idempotency_key is not None:
            existing = await self.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                return existing, False
        ticket = Ticket(
            id=new_id("tkt"),
            conversation_id=request.conversation_id,
            provider=provider,
            status=status,
            summary=request.summary,
            priority=request.priority,
            external_id=external_id,
            url=url,
            created_at=_NOW,
        )
        self.rows[ticket.id] = ticket
        if request.idempotency_key is not None:
            self.idempotency[request.idempotency_key] = ticket.id
        return ticket, True

    async def update(
        self,
        ticket_id: str,
        *,
        status: TicketStatus | None = None,
        external_id: str | None = None,
        url: str | None = None,
    ) -> Ticket | None:
        ticket = self.rows.get(ticket_id)
        if ticket is None:
            return None
        updates: dict[str, Any] = {}
        if status is not None:
            updates["status"] = status
        if external_id is not None:
            updates["external_id"] = external_id
        if url is not None:
            updates["url"] = url
        updated = ticket.model_copy(update=updates) if updates else ticket
        self.rows[ticket_id] = updated
        return updated


class InMemoryFeedback:
    """In-memory stand-in for ``FeedbackRepository`` used by ``FeedbackService`` (FR-052)."""

    def __init__(self) -> None:
        self.rows: list[Feedback] = []

    async def create(self, request: FeedbackRequest) -> Feedback:
        feedback = Feedback(
            id=new_id("fb"),
            conversation_id=request.conversation_id,
            rating=request.rating,
            comment=request.comment,
            resolution_outcome=request.resolution_outcome,
            created_at=_NOW,
        )
        self.rows.append(feedback)
        return feedback

    async def list_by_conversation(self, conversation_id: str) -> list[Feedback]:
        return [f for f in self.rows if f.conversation_id == conversation_id]

    async def report(self) -> FeedbackReport:
        by_rating: dict[int, int] = {}
        by_outcome: dict[Any, int] = {}
        for row in self.rows:
            by_rating[row.rating] = by_rating.get(row.rating, 0) + 1
            if row.resolution_outcome is not None:
                by_outcome[row.resolution_outcome] = by_outcome.get(row.resolution_outcome, 0) + 1
        average = round(sum(r.rating for r in self.rows) / len(self.rows), 2) if self.rows else None
        return FeedbackReport(
            total=len(self.rows),
            average_rating=average,
            by_rating=by_rating,
            by_outcome=by_outcome,
        )


class InMemoryAudit:
    def __init__(self) -> None:
        self.rows: list[AuditEvent] = []

    async def record(self, event: AuditEventCreate) -> AuditEvent:
        record = AuditEvent(
            id=new_id("aud"),
            event_type=event.event_type,
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            conversation_id=event.conversation_id,
            detail=event.detail,
            created_at=_NOW,
        )
        self.rows.append(record)
        return record


class _FakeRetriever:
    async def retrieve(self, query: object, *, tenant_id: str = "default") -> RetrievalResult:
        return RetrievalResult(
            query=str(query),
            hits=[
                RetrievalHit(
                    chunk=DocumentChunk(
                        id="chunk-1",
                        document_id="doc-1",
                        version=1,
                        chunk_index=0,
                        content="Refunds are available within 30 days of delivery.",
                        content_hash="hash-1",
                    ),
                    document_title="Refund Policy",
                    score=0.92,
                )
            ],
        )


class E2EStack:
    """Container for the wired stack so tests can assert on the in-memory state."""

    def __init__(
        self,
        *,
        chat: ChatService,
        conversations: ConversationService,
        tickets: TicketService,
        feedback: FeedbackService,
        graph: Any,
        adapter: MockTicketingAdapter,
        conversations_store: InMemoryConversations,
        tickets_store: InMemoryTickets,
        tool_executions: InMemoryToolExecutions,
        feedback_store: InMemoryFeedback,
        audit: InMemoryAudit,
    ) -> None:
        self.chat = chat
        self.conversations = conversations
        self.tickets = tickets
        self.feedback = feedback
        self.graph = graph
        self.adapter = adapter
        self.conversations_store = conversations_store
        self.tickets_store = tickets_store
        self.tool_executions = tool_executions
        self.feedback_store = feedback_store
        self.audit = audit


def _commerce() -> InMemoryCommerceAdapter:
    from decimal import Decimal

    from ecommerce_support.schemas import Order, OrderItem
    from ecommerce_support.schemas.enums import OrderStatus

    return InMemoryCommerceAdapter(
        orders=[
            Order(
                id="ord-1",
                customer_id="cust-1",
                status=OrderStatus.SHIPPED,
                currency="USD",
                total=Decimal("42.00"),
                placed_at=_NOW,
                items=[
                    OrderItem(
                        product_id="prd-1",
                        name="Wireless Mouse",
                        quantity=1,
                        unit_price=Decimal("42.00"),
                        line_total=Decimal("42.00"),
                    )
                ],
            )
        ],
    )


def _account() -> InMemoryAccountAdapter:
    return InMemoryAccountAdapter(
        profiles=[UserProfile(user_id="cust-1", email="ada@example.com", display_name="Ada")],
        order_counts={"cust-1": 2},
    )


@pytest.fixture
def e2e_stack() -> E2EStack:
    return _build_stack(MockTicketingAdapter())


@pytest.fixture
def e2e_stack_failing_tickets() -> E2EStack:
    return _build_stack(MockTicketingAdapter(always_fail=True))


def _build_stack(adapter: MockTicketingAdapter) -> E2EStack:
    conversations_store = InMemoryConversations()
    tool_executions = InMemoryToolExecutions()
    tickets_store = InMemoryTickets()
    feedback_store = InMemoryFeedback()
    audit = InMemoryAudit()

    graph = create_agent_graph(
        commerce=_commerce(),
        account=_account(),
        retriever=_FakeRetriever(),
        generator=GroundedGenerator(
            MockLLMClient(completions=["Refunds are available within 30 days [1]."])
        ),
        config=None,
        enable_llm_router=False,
    )
    ticket_service = TicketService(
        tickets=tickets_store,  # type: ignore[arg-type]
        conversations=conversations_store,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        adapter=adapter,
    )
    chat = ChatService(
        agents=graph,
        conversations=conversations_store,  # type: ignore[arg-type]
        escalations=EscalationAgent(),
        tickets=ticket_service,
        tool_executions=tool_executions,  # type: ignore[arg-type]
    )
    conversation_service = ConversationService(
        conversations_store,
        tool_executions,  # type: ignore[arg-type]
    )
    feedback_service = FeedbackService(
        feedback=feedback_store,  # type: ignore[arg-type]
        conversations=conversations_store,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )
    return E2EStack(
        chat=chat,
        conversations=conversation_service,
        tickets=ticket_service,
        feedback=feedback_service,
        graph=graph,
        adapter=adapter,
        conversations_store=conversations_store,
        tickets_store=tickets_store,
        tool_executions=tool_executions,
        feedback_store=feedback_store,
        audit=audit,
    )
