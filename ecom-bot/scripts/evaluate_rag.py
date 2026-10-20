"""Baseline RAG evaluation: ingest a corpus, run the versioned eval set, print metrics (FR-055).

Usage::

    uv run python -m scripts.evaluate_rag                 # defaults: evals/rag_dataset.yaml, evals/corpus
    uv run python -m scripts.evaluate_rag --tenant my-eval --keep

The corpus in ``--corpus`` is ingested into a throwaway tenant, every dataset case is run through
the real retriever + grounded generator, the report is printed, and the tenant is cleaned up
unless ``--keep`` is given. Requires a reachable database (``make db-up && make migrate``).

Offline baseline note: with the default mock embedding provider, vector distances are not
semantic, so the harness widens retrieval and relies on the deterministic lexical reranker to
surface relevant chunks. Retrieval recall is meaningful; abstention on unanswered questions is
best validated with a real embedding provider (set ``LLM__EMBEDDING_PROVIDER``) or by the
retrieval/generation integration tests.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from ecommerce_support.core.config import get_settings
from ecommerce_support.db.repositories import DocumentRepository
from ecommerce_support.db.session import close_engine, session_scope
from ecommerce_support.evaluation.rag import (
    DEFAULT_DATASET_PATH,
    RagEvaluator,
    load_eval_dataset,
    render_report,
)
from ecommerce_support.llm.factory import create_llm_client
from ecommerce_support.rag.embeddings import create_embedding_provider
from ecommerce_support.rag.generation import create_grounded_generator
from ecommerce_support.rag.ingestion import ingest_document
from ecommerce_support.rag.loaders import load_document
from ecommerce_support.rag.retrieval import Retriever

DEFAULT_CORPUS_PATH = Path("evals/corpus")

_OFFLINE_NOTE = (
    "offline baseline: mock embedder + lexical rerank, threshold disabled; "
    "abstention is best measured with a real embedding provider"
)


def _title_for(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the baseline RAG evaluation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--tenant", default="")
    parser.add_argument("--keep", action="store_true", help="do not clean up the eval tenant")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.0,
        help="exit non-zero when the pass rate is below this value",
    )
    return parser.parse_args(argv)


async def evaluate(args: argparse.Namespace) -> int:
    settings = get_settings()
    dataset = load_eval_dataset(args.dataset)
    corpus_files = sorted(p for p in args.corpus.glob("*") if p.is_file())
    if not corpus_files:
        raise SystemExit(f"No corpus files found under {args.corpus}")

    tenant = args.tenant or f"eval-{uuid4().hex[:8]}"
    embedder = create_embedding_provider(settings.llm)
    client = create_llm_client(settings.llm)

    async with session_scope() as session:
        for path in corpus_files:
            loaded = load_document(source=str(path), data=path.read_bytes(), filename=path.name)
            await ingest_document(
                session,
                loaded,
                tenant_id=tenant,
                title=_title_for(path),
                embedder=embedder,
                chunk_size=settings.rag.chunk_size,
                chunk_overlap=settings.rag.chunk_overlap,
            )

        retriever = Retriever.from_session(
            session,
            embedder,
            settings.rag.model_copy(update={"rerank_enabled": True, "rerank_top_n": 50}),
        )
        generator = create_grounded_generator(client, settings.rag, settings.guardrails)
        evaluator = RagEvaluator(
            retriever,
            generator,
            top_k=settings.rag.top_k,
            distance_threshold=None,
            tenant_id=tenant,
            notes=_OFFLINE_NOTE,
        )
        report = await evaluator.evaluate(dataset)

        print(render_report(report))

        if not args.keep:
            removed = await DocumentRepository(session).delete_by_tenant(tenant)
            print(f"cleaned up tenant {tenant} ({removed} documents)")

    return 0 if report.pass_rate >= args.min_pass_rate else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


async def _run(args: argparse.Namespace) -> int:
    try:
        return await evaluate(args)
    finally:
        await close_engine()


if __name__ == "__main__":
    raise SystemExit(main())
