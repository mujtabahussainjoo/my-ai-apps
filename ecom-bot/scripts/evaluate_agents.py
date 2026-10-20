"""Run the routing/tool-selection evaluation baseline (FR-055).

Wires the real agent graph to dependency-free in-memory adapters + the deterministic mock LLM so
the baseline runs with **no credentials and no network**, then prints intent-routing and
tool-selection accuracy for ``evals/routing_dataset.yaml``.

Usage::

    uv run python scripts/evaluate_agents.py
    uv run python scripts/evaluate_agents.py --min-routing-accuracy 1.0
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ecommerce_support.agents import create_agent_graph
from ecommerce_support.evaluation.routing import (
    DEFAULT_ROUTING_DATASET,
    RoutingEvaluator,
    load_routing_dataset,
    render_routing_report,
)
from ecommerce_support.integrations import InMemoryAccountAdapter, InMemoryCommerceAdapter
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.rag.generation import GroundedGenerator
from ecommerce_support.schemas import (
    DocumentChunk,
    Order,
    OrderItem,
    Product,
    RetrievalHit,
    RetrievalResult,
    UserProfile,
)
from ecommerce_support.schemas.enums import OrderStatus, StockStatus

_NOW = datetime(2026, 10, 19, tzinfo=UTC)


class _StaticRetriever:
    """Deterministic retriever returning one canned policy hit (no DB, no network)."""

    async def retrieve(self, query: object, *, tenant_id: str = "default") -> RetrievalResult:
        return RetrievalResult(
            query=str(getattr(query, "query", query)),
            hits=[
                RetrievalHit(
                    document_title="Refund Policy",
                    chunk=DocumentChunk(
                        id="chunk-refund-0",
                        document_id="doc-refund",
                        version=1,
                        chunk_index=0,
                        content=(
                            "Refunds are available within 30 days of delivery for unused items."
                        ),
                        content_hash="hash-refund-0",
                        section_title="Returns",
                    ),
                    score=0.9,
                )
            ],
        )


def _build_runner() -> object:
    commerce = InMemoryCommerceAdapter(
        products=[
            Product(
                id="prd-1",
                sku="SKU-HAMMER",
                name="Hammer",
                description="Steel claw hammer",
                category="tools",
                price=Decimal("12.00"),
                stock_status=StockStatus.IN_STOCK,
                stock_quantity=5,
            )
        ],
        orders=[
            Order(
                id="ord-1",
                customer_id="cust-1",
                status=OrderStatus.SHIPPED,
                total=Decimal("12.00"),
                placed_at=_NOW,
                items=[
                    OrderItem(
                        product_id="prd-1",
                        name="Hammer",
                        quantity=1,
                        unit_price=Decimal("12.00"),
                        line_total=Decimal("12.00"),
                    )
                ],
            )
        ],
    )
    account = InMemoryAccountAdapter(
        profiles=[UserProfile(user_id="cust-1", email="cust@example.com", display_name="Customer")],
        order_counts={"cust-1": 1},
    )
    return create_agent_graph(
        commerce=commerce,
        account=account,
        retriever=_StaticRetriever(),
        generator=GroundedGenerator(
            MockLLMClient(completions=["Refunds are available within 30 days [1]."])
        ),
        enable_llm_router=False,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the routing evaluation baseline.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_ROUTING_DATASET)
    parser.add_argument("--min-routing-accuracy", type=float, default=0.0)
    parser.add_argument("--min-tool-accuracy", type=float, default=0.0)
    return parser.parse_args(argv)


async def evaluate(args: argparse.Namespace) -> int:
    dataset = load_routing_dataset(args.dataset)
    evaluator = RoutingEvaluator(
        _build_runner(),  # type: ignore[arg-type]
        notes="offline baseline: deterministic rules + mock LLM",
    )
    report = await evaluator.evaluate(dataset)
    print(render_routing_report(report))
    ok = (
        report.routing_accuracy >= args.min_routing_accuracy
        and report.tool_selection_accuracy >= args.min_tool_accuracy
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(evaluate(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
