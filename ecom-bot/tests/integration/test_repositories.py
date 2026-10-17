"""Integration tests for the repository layer (TASK-010).

Run against the compose database with migrations applied (`make db-up && make migrate`);
skipped automatically when it is unreachable. Every test executes inside a transaction that
is rolled back, so no rows persist.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.core.ids import new_id
from ecommerce_support.db.repositories import (
    AuditEventRepository,
    ConversationRepository,
    DocumentRepository,
    EvalResultRepository,
    FeedbackRepository,
    OrderRepository,
    ProductRepository,
    TicketRepository,
    ToolExecutionRepository,
    UserRepository,
)
from ecommerce_support.schemas import (
    Address,
    AuditEventCreate,
    DocumentChunk,
    EvalResultCreate,
    FeedbackRequest,
    Order,
    OrderItem,
    Product,
    ProductSearchQuery,
    TicketRequest,
)
from ecommerce_support.schemas.enums import (
    AgentName,
    ConversationStatus,
    DocumentStatus,
    MessageRole,
    OrderStatus,
    Priority,
    ResolutionOutcome,
    StockStatus,
    TicketProvider,
    TicketStatus,
    ToolCallStatus,
)

pytestmark = pytest.mark.integration

EMBEDDING_DIM = 1536


def _embedding(value: float = 0.1) -> list[float]:
    return [value] * EMBEDDING_DIM


async def _make_user(session: AsyncSession, user_id: str = "usr-1") -> None:
    await UserRepository(session).upsert(
        user_id=user_id, email="Customer@Example.com", display_name="Ada"
    )


async def _make_product(
    session: AsyncSession,
    product_id: str = "prd-1",
    *,
    sku: str = "SKU-1",
    name: str = "Widget",
    category: str = "tools",
    price: str = "9.99",
) -> None:
    await ProductRepository(session).upsert_many(
        [
            Product(
                id=product_id,
                sku=sku,
                name=name,
                category=category,
                price=Decimal(price),
                stock_status=StockStatus.IN_STOCK,
                stock_quantity=5,
            )
        ]
    )


async def _make_conversation(
    session: AsyncSession, *, user_id: str | None = "usr-1", conversation_id: str | None = None
) -> str:
    conversation = await ConversationRepository(session).create(
        user_id=user_id, conversation_id=conversation_id
    )
    return conversation.id


async def test_user_upsert_is_normalized_and_updates(session: AsyncSession) -> None:
    repo = UserRepository(session)
    created = await repo.upsert(user_id="usr-1", email="Customer@Example.com", display_name="Ada")
    assert created.email == "customer@example.com"

    fetched = await repo.get("usr-1")
    assert fetched is not None
    assert fetched.display_name == "Ada"

    updated = await repo.upsert(user_id="usr-1", email="OTHER@Example.com", display_name="Grace")
    assert updated.email == "other@example.com"
    assert updated.display_name == "Grace"
    assert (await repo.get("usr-1")).display_name == "Grace"  # type: ignore[union-attr]


async def test_conversation_message_lifecycle(session: AsyncSession) -> None:
    await _make_user(session)
    repo = ConversationRepository(session)
    conversation_id = await _make_conversation(session)

    await repo.append_message(conversation_id, role=MessageRole.USER, content="Where is my order?")
    await repo.append_message(
        conversation_id,
        role=MessageRole.ASSISTANT,
        content="Let me check.",
        agent=AgentName.ORDER,
    )

    conversation = await repo.get(conversation_id)
    assert conversation is not None
    assert len(conversation.messages) == 2
    assert {m.content for m in conversation.messages} == {"Where is my order?", "Let me check."}

    summary = await repo.get_summary(conversation_id)
    assert summary is not None
    assert summary.message_count == 2

    await repo.update_status(
        conversation_id,
        ConversationStatus.RESOLVED,
        resolution_outcome=ResolutionOutcome.RESOLVED,
    )
    assert (await repo.get(conversation_id)).status == ConversationStatus.RESOLVED  # type: ignore[union-attr]

    listed, total = await repo.list_for_user("usr-1")
    assert total == 1
    assert listed[0].message_count == 2


async def test_conversation_update_status_missing_raises(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await ConversationRepository(session).update_status("conv-missing", ConversationStatus.OPEN)


async def test_product_search_and_stock(session: AsyncSession) -> None:
    repo = ProductRepository(session)
    marker = uuid4().hex[:8]
    category = f"test-cat-{marker}"
    await _make_product(
        session,
        f"prd-{marker}-1",
        sku=f"SKU-{marker}-1",
        name="Widget",
        category=category,
        price="9.99",
    )
    await _make_product(
        session,
        f"prd-{marker}-2",
        sku=f"SKU-{marker}-2",
        name="Gadget",
        category=category,
        price="49.99",
    )
    await _make_product(
        session,
        f"prd-{marker}-3",
        sku=f"SKU-{marker}-3",
        name="Lamp",
        category=category,
        price="19.99",
    )

    hits, total = await repo.search(ProductSearchQuery(query="wid", category=category))
    assert total == 1
    assert hits[0].sku == f"SKU-{marker}-1"

    hits, total = await repo.search(ProductSearchQuery(category=category))
    assert total == 3

    hits, total = await repo.search(
        ProductSearchQuery(
            category=category, min_price=Decimal("10.00"), max_price=Decimal("20.00")
        )
    )
    assert total == 1
    assert hits[0].name == "Lamp"

    _, total = await repo.list_products(limit=100)
    assert total >= 3

    assert (await repo.get_by_sku(f"SKU-{marker}-2")).name == "Gadget"  # type: ignore[union-attr]
    stock = await repo.stock_info(f"prd-{marker}-1")
    assert stock is not None
    assert stock.status == StockStatus.IN_STOCK
    assert stock.quantity == 5


async def test_order_upsert_replaces_items(session: AsyncSession) -> None:
    await _make_user(session)
    await _make_product(session, "prd-1", sku="SKU-1", name="Widget")
    await _make_product(session, "prd-2", sku="SKU-2", name="Gadget")
    repo = OrderRepository(session)

    order = Order(
        id="ord-1",
        customer_id="usr-1",
        status=OrderStatus.SHIPPED,
        total=Decimal("29.98"),
        placed_at=datetime(2026, 1, 1, tzinfo=UTC),
        shipping_address=Address(
            line1="1 Main St", city="Springfield", postal_code="12345", country="US"
        ),
        items=[
            OrderItem(
                product_id="prd-1",
                name="Widget",
                quantity=2,
                unit_price=Decimal("9.99"),
                line_total=Decimal("19.98"),
            ),
            OrderItem(
                product_id="prd-2",
                name="Gadget",
                quantity=1,
                unit_price=Decimal("10.00"),
                line_total=Decimal("10.00"),
            ),
        ],
    )
    created = await repo.upsert(order)
    assert created.shipping_address is not None
    assert created.shipping_address.city == "Springfield"

    fetched = await repo.get("ord-1")
    assert fetched is not None
    assert len(fetched.items) == 2

    summaries, total = await repo.list_for_customer("usr-1")
    assert total == 1
    assert summaries[0].item_count == 2

    order.items = [
        OrderItem(
            product_id="prd-1",
            name="Widget",
            quantity=1,
            unit_price=Decimal("9.99"),
            line_total=Decimal("9.99"),
        )
    ]
    await repo.upsert(order)
    refetched = await repo.get("ord-1")
    assert refetched is not None
    assert len(refetched.items) == 1


async def test_feedback_create_and_reports(session: AsyncSession) -> None:
    await _make_user(session)
    conversation_id = await _make_conversation(session)
    repo = FeedbackRepository(session)

    first = await repo.create(
        FeedbackRequest(
            conversation_id=conversation_id,
            rating=5,
            comment="  great  ",
            resolution_outcome=ResolutionOutcome.RESOLVED,
        )
    )
    await repo.create(
        FeedbackRequest(
            conversation_id=conversation_id,
            rating=3,
            resolution_outcome=ResolutionOutcome.UNRESOLVED,
        )
    )

    assert first.comment == "great"
    assert (await repo.get(first.id)) is not None
    assert len(await repo.list_by_conversation(conversation_id)) == 2
    assert await repo.count_by_rating() == {3: 1, 5: 1}
    outcomes = await repo.count_by_outcome()
    assert outcomes[ResolutionOutcome.RESOLVED] == 1
    assert outcomes[ResolutionOutcome.UNRESOLVED] == 1


async def test_feedback_rating_check_constraint_enforced(session: AsyncSession) -> None:
    await _make_user(session)
    conversation_id = await _make_conversation(session)
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text("INSERT INTO feedback (id, conversation_id, rating) VALUES (:id, :cid, 9)"),
                {"id": new_id("fb"), "cid": conversation_id},
            )


async def test_ticket_creation_is_idempotent(session: AsyncSession) -> None:
    await _make_user(session)
    conversation_id = await _make_conversation(session)
    repo = TicketRepository(session)
    idempotency_key = f"idem-{uuid4().hex[:12]}"
    request = TicketRequest(
        conversation_id=conversation_id,
        summary="Refund not received",
        priority=Priority.HIGH,
        idempotency_key=idempotency_key,
    )

    ticket, created = await repo.create_idempotent(
        request, provider=TicketProvider.JIRA, status=TicketStatus.PENDING
    )
    assert created is True

    repeat, created_again = await repo.create_idempotent(
        request, provider=TicketProvider.JIRA, status=TicketStatus.PENDING
    )
    assert created_again is False
    assert repeat.id == ticket.id

    assert (await repo.get_by_idempotency_key(idempotency_key)).id == ticket.id  # type: ignore[union-attr]

    updated = await repo.update(
        ticket.id, status=TicketStatus.CREATED, external_id="JIRA-1", url="https://jira/1"
    )
    assert updated is not None
    assert updated.status == TicketStatus.CREATED
    assert updated.external_id == "JIRA-1"
    assert len(await repo.list_by_conversation(conversation_id)) == 1


async def test_document_versioning_and_chunks(session: AsyncSession) -> None:
    repo = DocumentRepository(session)
    tenant = f"test-tenant-{uuid4().hex[:8]}"
    v1 = await repo.create(
        title="Return Policy",
        source="policies/returns.md",
        version=1,
        content_hash="hash-v1",
        tenant_id=tenant,
    )
    v2 = await repo.create(
        title="Return Policy",
        source="policies/returns.md",
        version=2,
        content_hash="hash-v2",
        tenant_id=tenant,
    )

    assert (
        await repo.get_by_source_version(tenant_id=tenant, source="policies/returns.md", version=1)
    ).id == v1.id  # type: ignore[union-attr]

    chunks = [
        DocumentChunk(
            id=new_id("chk"),
            document_id=v2.id,
            version=2,
            chunk_index=index,
            content=f"chunk {index}",
            content_hash=f"c-{index}",
            section_title="Returns",
            token_count=10,
        )
        for index in range(2)
    ]
    stored = await repo.replace_chunks(v2.id, chunks, embeddings=[_embedding(), _embedding(0.2)])
    assert stored == 2

    listed = await repo.list_chunks(v2.id)
    assert [c.chunk_index for c in listed] == [0, 1]

    dims = await session.scalar(
        text("SELECT vector_dims(embedding) FROM document_chunks WHERE document_id = :d LIMIT 1"),
        {"d": v2.id},
    )
    assert dims == EMBEDDING_DIM

    _, total = await repo.list_documents(tenant_id=tenant)
    assert total == 2

    superseded = await repo.supersede(v1.id)
    assert superseded is not None
    assert superseded.status == DocumentStatus.SUPERSEDED

    assert await repo.delete_chunks(v2.id) == 2
    assert await repo.list_chunks(v2.id) == []


async def test_audit_events_are_recorded_in_order(session: AsyncSession) -> None:
    await _make_user(session)
    conversation_id = await _make_conversation(session)
    repo = AuditEventRepository(session)

    await repo.record(
        AuditEventCreate(event_type="conversation.opened", conversation_id=conversation_id)
    )
    await repo.record(
        AuditEventCreate(
            event_type="tool.invoked",
            actor_id="usr-1",
            resource_type="order",
            resource_id="ord-1",
            conversation_id=conversation_id,
            detail={"tool": "get_order"},
        )
    )

    events = await repo.list_for_conversation(conversation_id)
    assert [e.event_type for e in events] == ["conversation.opened", "tool.invoked"]
    assert events[1].detail == {"tool": "get_order"}


async def test_tool_executions_are_recorded(session: AsyncSession) -> None:
    await _make_user(session)
    conversation_id = await _make_conversation(session)
    repo = ToolExecutionRepository(session)

    await repo.record(
        tool_name="get_order",
        call_id="call-1",
        status=ToolCallStatus.OK,
        conversation_id=conversation_id,
        summary="order ord-1",
        duration_ms=12.5,
    )
    executions = await repo.list_for_conversation(conversation_id)
    assert len(executions) == 1
    assert executions[0].tool_name == "get_order"
    assert executions[0].status == ToolCallStatus.OK


async def test_eval_results_record_and_filter(session: AsyncSession) -> None:
    repo = EvalResultRepository(session)
    dataset = f"v-{uuid4().hex[:8]}"
    await repo.record_many(
        [
            EvalResultCreate(
                dataset_version=dataset, case_id="c1", metric="faithfulness", score=0.9
            ),
            EvalResultCreate(
                dataset_version=dataset, case_id="c1", metric="answer_relevancy", score=0.8
            ),
            EvalResultCreate(
                dataset_version=dataset, case_id="c2", metric="faithfulness", score=0.7
            ),
        ]
    )

    assert len(await repo.list_by_dataset(dataset)) == 3
    faithfulness = await repo.list_by_dataset(dataset, metric="faithfulness")
    assert len(faithfulness) == 2
    assert all(r.metric == "faithfulness" for r in faithfulness)


async def test_enum_check_constraint_enforced(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text("INSERT INTO conversations (id, status) VALUES (:id, :status)"),
                {"id": new_id("conv"), "status": "NOT_A_STATUS"},
            )
