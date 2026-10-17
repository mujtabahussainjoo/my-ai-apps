"""Tests for shared Pydantic contracts: construction, validators, and constraints."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ecommerce_support.schemas import (
    MAX_MESSAGE_CHARS,
    AgentState,
    ChatRequest,
    ConversationStatus,
    ErrorResponse,
    FeedbackRequest,
    Order,
    OrderItem,
    Page,
    PageParams,
    ProductSearchQuery,
    RetrievalResult,
    Schema,
    SourceCitation,
    TicketRequest,
    UserProfile,
)

_NOW = datetime(2026, 10, 17, tzinfo=UTC)


# --- base / common -----------------------------------------------------------


class TestSchemaBase:
    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="hi", unexpected="x")

    def test_strips_whitespace(self) -> None:
        assert ChatRequest(message="  hi there  ").message == "hi there"

    def test_instances_are_independent(self) -> None:
        a = AgentState(conversation_id="c1")
        b = AgentState(conversation_id="c2")
        a.evidence.append(SourceCitation(document_id="d", chunk_id="k", score=1.0))
        assert b.evidence == []


class TestPage:
    def test_has_more_true(self) -> None:
        page = Page[int](items=[1, 2], total=5, limit=2, offset=0)
        assert page.has_more is True

    def test_has_more_false_on_last_page(self) -> None:
        page = Page[int](items=[4, 5], total=5, limit=2, offset=3)
        assert page.has_more is False

    def test_params_bounds(self) -> None:
        assert PageParams().limit == 20
        with pytest.raises(ValidationError):
            PageParams(limit=0)
        with pytest.raises(ValidationError):
            PageParams(limit=101)
        with pytest.raises(ValidationError):
            PageParams(offset=-1)


class TestErrorResponse:
    def test_matches_api_envelope_shape(self) -> None:
        resp = ErrorResponse.model_validate(
            {
                "error": {
                    "code": "not_found",
                    "message": "missing",
                    "details": {"id": "o1"},
                    "retryable": False,
                },
                "request_id": "req_1",
            }
        )
        assert resp.error.code == "not_found"
        assert resp.error.details == {"id": "o1"}
        assert resp.request_id == "req_1"


# --- chat --------------------------------------------------------------------


class TestChatRequest:
    def test_defaults(self) -> None:
        req = ChatRequest(message="where is my order?")
        assert req.stream is True
        assert req.conversation_id is None

    def test_blank_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="   ")

    def test_empty_message_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="")

    def test_message_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(message="x" * (MAX_MESSAGE_CHARS + 1))

    def test_max_length_boundary_accepted(self) -> None:
        assert len(ChatRequest(message="x" * MAX_MESSAGE_CHARS).message) == MAX_MESSAGE_CHARS


# --- agents ------------------------------------------------------------------


class TestAgentContracts:
    def test_state_counters_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            AgentState(conversation_id="c1", retry_count=-1)

    def test_citation_score_and_version_bounds(self) -> None:
        with pytest.raises(ValidationError):
            SourceCitation(document_id="d", chunk_id="k", score=-0.1)
        with pytest.raises(ValidationError):
            SourceCitation(document_id="d", chunk_id="k", score=0.5, version=0)
        citation = SourceCitation(document_id="d", chunk_id="k", score=0.0)
        assert citation.score == 0.0


# --- commerce -----------------------------------------------------------------


class TestCommerceContracts:
    def test_order_item_rejects_bad_quantity_and_price(self) -> None:
        with pytest.raises(ValidationError):
            OrderItem(
                product_id="p1",
                name="Thing",
                quantity=0,
                unit_price=Decimal("1.00"),
                line_total=Decimal("0.00"),
            )
        with pytest.raises(ValidationError):
            OrderItem(
                product_id="p1",
                name="Thing",
                quantity=1,
                unit_price=Decimal("-1.00"),
                line_total=Decimal("0.00"),
            )

    def test_order_rejects_bad_currency(self) -> None:
        with pytest.raises(ValidationError):
            Order(
                id="o1",
                customer_id="u1",
                status="delivered",
                currency="usd",
                total=Decimal("10.00"),
                placed_at=_NOW,
            )

    def test_order_accepts_valid_payload(self) -> None:
        order = Order(
            id="o1",
            customer_id="u1",
            status="shipped",
            total=Decimal("19.99"),
            placed_at=_NOW,
            items=[
                OrderItem(
                    product_id="p1",
                    name="Thing",
                    quantity=2,
                    unit_price=Decimal("9.99"),
                    line_total=Decimal("19.98"),
                )
            ],
        )
        assert order.currency == "USD"
        assert order.items[0].quantity == 2


class TestProductSearchQuery:
    def test_min_greater_than_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProductSearchQuery(min_price=Decimal("10"), max_price=Decimal("5"))

    def test_equal_bounds_accepted(self) -> None:
        query = ProductSearchQuery(min_price=Decimal("5"), max_price=Decimal("5"))
        assert query.min_price == query.max_price

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProductSearchQuery(min_price=Decimal("-1"))


# --- accounts ----------------------------------------------------------------


class TestUserProfile:
    def test_email_lowercased(self) -> None:
        profile = UserProfile(user_id="u1", email="Customer@Example.COM")
        assert profile.email == "customer@example.com"

    def test_invalid_email_rejected(self) -> None:
        with pytest.raises(ValidationError):
            UserProfile(user_id="u1", email="not-an-email")


# --- feedback ----------------------------------------------------------------


class TestFeedbackRequest:
    @pytest.mark.parametrize("rating", [1, 3, 5])
    def test_valid_ratings(self, rating: int) -> None:
        assert FeedbackRequest(conversation_id="c1", rating=rating).rating == rating

    @pytest.mark.parametrize("rating", [0, 6, -1])
    def test_invalid_ratings(self, rating: int) -> None:
        with pytest.raises(ValidationError):
            FeedbackRequest(conversation_id="c1", rating=rating)

    def test_blank_comment_becomes_none(self) -> None:
        assert FeedbackRequest(conversation_id="c1", rating=4, comment="   ").comment is None

    def test_comment_is_trimmed(self) -> None:
        assert FeedbackRequest(conversation_id="c1", rating=4, comment="  thanks  ").comment == (
            "thanks"
        )


# --- tickets -----------------------------------------------------------------


class TestTicketRequest:
    def test_defaults(self) -> None:
        ticket = TicketRequest(conversation_id="c1", summary="Broken delivery")
        assert ticket.priority == "medium"
        assert ticket.requires_confirmation is False

    def test_summary_required(self) -> None:
        with pytest.raises(ValidationError):
            TicketRequest(conversation_id="c1", summary="")

    def test_idempotency_key_length_bounded(self) -> None:
        with pytest.raises(ValidationError):
            TicketRequest(conversation_id="c1", summary="x", idempotency_key="k" * 129)


# --- documents ---------------------------------------------------------------


class TestRetrievalResult:
    def test_abstained_when_empty(self) -> None:
        result = RetrievalResult(query="returns?", abstained=True)
        assert result.is_empty is True

    def test_not_empty_with_hits(self) -> None:
        from ecommerce_support.schemas import DocumentChunk, RetrievalHit

        hit = RetrievalHit(
            chunk=DocumentChunk(
                id="ch1",
                document_id="d1",
                version=1,
                chunk_index=0,
                content="Returns accepted within 30 days.",
                content_hash="abc",
            ),
            document_title="Return Policy",
            score=0.9,
        )
        result = RetrievalResult(query="returns?", hits=[hit])
        assert result.is_empty is False
        assert result.hits[0].chunk.document_id == "d1"


# --- enums -------------------------------------------------------------------


def test_conversation_status_matches_fr047() -> None:
    assert ConversationStatus.TICKET_CREATION_FAILED.value == "TICKET_CREATION_FAILED"
    assert ConversationStatus.AWAITING_CUSTOMER.value == "AWAITING_CUSTOMER"


def test_schema_rejects_extra_only() -> None:
    class _Thing(Schema):
        value: int

    with pytest.raises(ValidationError):
        _Thing(value=1, extra=2)
