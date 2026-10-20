"""Unit tests for the LangGraph orchestration: routing, fallback, bounded execution (TASK-027)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from ecommerce_support.agents import AgentGraph, create_agent_graph
from ecommerce_support.core.config import AgentsConfig
from ecommerce_support.integrations import (
    InMemoryAccountAdapter,
    InMemoryCommerceAdapter,
)
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.rag.generation import GroundedGenerator
from ecommerce_support.schemas import (
    Order,
    OrderItem,
    OrderStatus,
    Product,
    StockStatus,
    UserProfile,
)
from ecommerce_support.schemas.agents import AgentState
from ecommerce_support.schemas.documents import DocumentChunk, RetrievalHit, RetrievalResult
from ecommerce_support.schemas.enums import AgentName, ResolutionAction, ResolutionOutcome


def _commerce() -> InMemoryCommerceAdapter:
    return InMemoryCommerceAdapter(
        products=[
            Product(
                id="prd-1",
                sku="SKU-1",
                name="Hammer",
                category="tools",
                price=Decimal("9.99"),
                stock_status=StockStatus.IN_STOCK,
                stock_quantity=2,
            )
        ],
        orders=[
            Order(
                id="ord-1",
                customer_id="cust-1",
                status=OrderStatus.DELIVERED,
                total=Decimal("9.99"),
                placed_at=datetime(2026, 10, 1, tzinfo=UTC),
                items=[
                    OrderItem(
                        product_id="prd-1",
                        name="Hammer",
                        quantity=1,
                        unit_price=Decimal("9.99"),
                        line_total=Decimal("9.99"),
                    )
                ],
            )
        ],
    )


def _account() -> InMemoryAccountAdapter:
    return InMemoryAccountAdapter(
        profiles=[UserProfile(user_id="cust-1", email="cust1@example.com", display_name="Ada")],
        order_counts={"cust-1": 1},
    )


class _FakeRetriever:
    async def retrieve(self, query: object, *, tenant_id: str = "default") -> RetrievalResult:
        return RetrievalResult(
            query="q",
            hits=[
                RetrievalHit(
                    chunk=DocumentChunk(
                        id="chunk-1",
                        document_id="doc-1",
                        version=1,
                        chunk_index=0,
                        content="Refunds within 30 days.",
                        content_hash="h1",
                    ),
                    document_title="Refund Policy",
                    score=0.9,
                )
            ],
        )


def _graph(
    *, completions: list[str] | None = None, config: AgentsConfig | None = None
) -> AgentGraph:
    return create_agent_graph(
        commerce=_commerce(),
        account=_account(),
        retriever=_FakeRetriever(),  # type: ignore[arg-type]
        generator=GroundedGenerator(
            MockLLMClient(completions=completions or ["Refunds within 30 days [1]."])
        ),
        config=config,
        enable_llm_router=False,
    )


class _AbstainRetriever:
    async def retrieve(self, query: object, *, tenant_id: str = "default") -> RetrievalResult:
        return RetrievalResult(query="q", hits=[])


def _state(message: str, **overrides: object) -> AgentState:
    data: dict[str, object] = {
        "conversation_id": "conv-1",
        "user_id": "cust-1",
        "message": message,
    }
    data.update(overrides)
    return AgentState(**data)


class TestRouting:
    async def test_order_with_id(self) -> None:
        result = await _graph().ainvoke(_state("Where is my order ord-1?"))
        assert result.selected_agent is AgentName.ORDER
        assert result.intent is not None and result.intent.value == "order"
        assert "ord-1" in (result.answer or "")

    async def test_order_without_id_lists(self) -> None:
        result = await _graph().ainvoke(_state("Show me my orders"))
        assert "order(s)" in (result.answer or "")

    async def test_product_search(self) -> None:
        result = await _graph().ainvoke(_state("Do you sell hammer?"))
        assert result.selected_agent is AgentName.PRODUCT
        assert "Hammer" in (result.answer or "")

    async def test_product_stock_by_id(self) -> None:
        result = await _graph().ainvoke(_state("Is prd-1 in stock?"))
        assert "in_stock" in (result.answer or "")

    async def test_policy_round_trip(self) -> None:
        result = await _graph().ainvoke(_state("What is your refund policy?"))
        assert result.selected_agent is AgentName.POLICY
        assert len(result.evidence) == 1
        assert result.error is None

    async def test_account_profile(self) -> None:
        result = await _graph().ainvoke(_state("Show me my account"))
        assert result.selected_agent is AgentName.ACCOUNT
        assert "Ada" in (result.answer or "")

    async def test_general_greeting(self) -> None:
        result = await _graph().ainvoke(_state("hello there"))
        assert result.selected_agent is AgentName.GENERAL
        assert result.needs_clarification is False


class TestFallback:
    async def test_ambiguous_clarifies(self) -> None:
        result = await _graph().ainvoke(_state("mumble mumble"))
        assert result.needs_clarification is True
        assert "more detail" in (result.answer or "")

    async def test_requires_auth_without_user(self) -> None:
        result = await _graph().ainvoke(_state("Where is my order ord-1?", user_id=None))
        assert "sign in" in (result.answer or "").lower()

    async def test_worker_failure_is_contained(self) -> None:
        graph = _graph(config=AgentsConfig(max_retry_attempts=0))

        async def _boom(*args: object, **kwargs: object) -> object:
            raise RuntimeError("kaboom")

        graph._policy.answer = _boom  # type: ignore[method-assign,assignment]
        result = await graph.ainvoke(_state("What is your refund policy?"))
        assert result.error == "worker_failed"
        assert result.escalation_requested is True
        assert "human agent" in (result.answer or "")
        assert result.resolution_state is ResolutionOutcome.UNRESOLVED


class TestResolutionFlow:
    async def test_answer_prompts_for_resolution(self) -> None:
        result = await _graph().ainvoke(_state("Where is my order ord-1?"))
        assert result.resolution_action is ResolutionAction.AWAIT_CUSTOMER
        assert result.resolution_state is None
        assert "Did that resolve your issue?" in (result.answer or "")

    async def test_clarify_does_not_double_prompt(self) -> None:
        result = await _graph().ainvoke(_state("mumble mumble"))
        assert result.resolution_action is ResolutionAction.AWAIT_CUSTOMER
        assert "Did that resolve your issue?" not in (result.answer or "")

    async def test_worker_failure_retries_alternative_agent(self) -> None:
        graph = _graph()

        async def _boom(*args: object, **kwargs: object) -> object:
            raise RuntimeError("kaboom")

        graph._order.get_order = _boom  # type: ignore[method-assign,assignment]
        result = await graph.ainvoke(_state("Where is my order ord-1?"))
        assert result.retry_count == 1
        assert result.selected_agent is AgentName.POLICY
        assert result.error is None
        assert result.resolution_action is ResolutionAction.AWAIT_CUSTOMER
        assert result.attempts == ["worker_failed", "insufficient_evidence"]

    async def test_abstention_escalates_when_retries_disabled(self) -> None:
        graph = create_agent_graph(
            commerce=_commerce(),
            account=_account(),
            retriever=_AbstainRetriever(),  # type: ignore[arg-type]
            generator=GroundedGenerator(MockLLMClient(completions=["unused"])),
            config=AgentsConfig(max_retry_attempts=0),
            enable_llm_router=False,
        )
        result = await graph.ainvoke(_state("What is your refund policy?"))
        assert result.abstained is True
        assert result.escalation_requested is True
        assert result.resolution_state is ResolutionOutcome.UNRESOLVED
        assert "ticket reference" in (result.answer or "")

    async def test_human_request_escalates_directly(self) -> None:
        result = await _graph().ainvoke(_state("I want to talk to a human"))
        assert result.selected_agent is AgentName.ESCALATION
        assert result.escalation_requested is True
        assert result.resolution_state is ResolutionOutcome.UNRESOLVED


class TestBoundedExecution:
    async def test_iteration_limit_is_enforced(self) -> None:
        config = AgentsConfig(max_graph_iterations=1, max_routing_hops=3)
        graph = _graph(config=config)
        result = await graph.ainvoke(_state("Where is my order ord-1?", iterations=5))
        assert result.error == "max_iterations_exceeded"
        assert "human agent" in (result.answer or "")

    async def test_routing_hop_limit_is_enforced(self) -> None:
        config = AgentsConfig(max_graph_iterations=8, max_routing_hops=1)
        graph = _graph(config=config)
        result = await graph.ainvoke(_state("Where is my order ord-1?", hop_count=5))
        assert result.error == "max_routing_hops_exceeded"

    async def test_at_limit_iteration_is_allowed(self) -> None:
        config = AgentsConfig(max_graph_iterations=2, max_routing_hops=3)
        graph = _graph(config=config)
        result = await graph.ainvoke(_state("hello there", iterations=1))
        assert result.error is None
        assert result.iterations == 2
