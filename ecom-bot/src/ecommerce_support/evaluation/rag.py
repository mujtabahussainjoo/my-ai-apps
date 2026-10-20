"""Evaluation harness: RAG dataset loading and metric scoring (FR-055).

The harness is pipeline-agnostic: it takes any object with ``retrieve`` and any object with
``answer``, so it runs against the real retriever/generator or deterministic fakes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError as PydanticValidationError

from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.schemas.documents import (
    GroundedAnswer,
    RetrievalQuery,
    RetrievalResult,
)
from ecommerce_support.schemas.eval import RagCaseScore, RagEvalCase, RagEvalDataset, RagEvalReport

__all__ = [
    "DEFAULT_DATASET_PATH",
    "GeneratorLike",
    "RagEvaluator",
    "RetrieverLike",
    "load_eval_dataset",
    "render_report",
    "score_case",
]

DEFAULT_DATASET_PATH = Path("evals/rag_dataset.yaml")

_YAML_SUFFIXES = {".yaml", ".yml"}


class RetrieverLike(Protocol):
    """Anything that can answer a retrieval request (the real retriever or a test double)."""

    async def retrieve(
        self, query: str | RetrievalQuery, *, tenant_id: str = ...
    ) -> RetrievalResult: ...


class GeneratorLike(Protocol):
    """Anything that can turn a retrieval result into a grounded answer."""

    async def answer(self, query: str, retrieval: RetrievalResult) -> GroundedAnswer: ...


def load_eval_dataset(path: str | Path | None = None) -> RagEvalDataset:
    """Load and validate a versioned RAG eval dataset (``.yaml``/``.yml`` or ``.json``)."""
    dataset_path = Path(path) if path is not None else DEFAULT_DATASET_PATH
    if not dataset_path.is_file():
        raise ConfigurationError(
            "RAG eval dataset not found.",
            details={"path": str(dataset_path)},
        )
    suffix = dataset_path.suffix.lower()
    text = dataset_path.read_text(encoding="utf-8")
    try:
        if suffix == ".json":
            data = json.loads(text)
        elif suffix in _YAML_SUFFIXES:
            data = yaml.safe_load(text)
        else:
            raise ConfigurationError(
                "Unsupported eval dataset format (use .yaml, .yml, or .json).",
                details={"path": str(path)},
            )
    except (ValueError, yaml.YAMLError) as exc:
        raise ConfigurationError(
            "Could not parse the RAG eval dataset.",
            details={"path": str(path)},
        ) from exc
    if not isinstance(data, dict):
        raise ConfigurationError(
            "The RAG eval dataset must be a mapping with 'version' and 'cases'.",
            details={"path": str(path)},
        )
    try:
        return RagEvalDataset.model_validate(data)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            "Invalid RAG eval dataset.",
            details={"errors": exc.error_count()},
        ) from exc


def _matches(title: str, expected: str) -> bool:
    return expected.casefold() in title.casefold()


def _evidence_text(result: RetrievalResult) -> str:
    return "\n".join(hit.chunk.content for hit in result.hits)


def score_case(
    case: RagEvalCase, retrieval: RetrievalResult, answer: GroundedAnswer
) -> RagCaseScore:
    """Score one case against its retrieval result and grounded answer."""
    expected = [doc for doc in case.expected_documents if doc.strip()]
    matched = [
        doc for doc in expected if any(_matches(hit.document_title, doc) for hit in retrieval.hits)
    ]
    recall = 1.0 if not expected else len(matched) / len(expected)

    quote_found = (
        case.expected_quote is None
        or case.expected_quote.casefold() in _evidence_text(retrieval).casefold()
    )
    abstention_correct = 1.0 if answer.abstained == case.should_abstain else 0.0
    if case.should_abstain:
        groundedness = 1.0 if answer.abstained else 0.0
    else:
        groundedness = 1.0 if (not answer.abstained and answer.answer and answer.citations) else 0.0
    passed = recall == 1.0 and quote_found and groundedness == 1.0 and abstention_correct == 1.0

    return RagCaseScore(
        case_id=case.id,
        recall=recall,
        groundedness=groundedness,
        abstention_correct=abstention_correct,
        citation_count=len(answer.citations),
        abstained=answer.abstained,
        passed=passed,
        detail={
            "expected_documents": expected,
            "matched_documents": matched,
            "retrieved_titles": [hit.document_title for hit in retrieval.hits],
            "expected_quote": case.expected_quote,
            "answer_reason": answer.reason,
        },
    )


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def render_report(report: RagEvalReport) -> str:
    """Render a human-readable report."""
    lines = [
        f"RAG evaluation — dataset {report.dataset_version} ({report.case_count} cases)",
        f"  recall={report.mean_recall:.3f}  groundedness={report.mean_groundedness:.3f}  "
        f"abstention={report.abstention_accuracy:.3f}  pass_rate={report.pass_rate:.3f}",
    ]
    for score in report.scores:
        lines.append(
            f"  - {score.case_id}: recall={score.recall:.2f} groundedness={score.groundedness:.2f} "
            f"abstention={score.abstention_correct:.2f} cites={score.citation_count} "
            f"{'PASS' if score.passed else 'FAIL'}"
        )
    if report.notes:
        lines.append(f"  note: {report.notes}")
    return "\n".join(lines)


class RagEvaluator:
    """Runs a dataset through a retriever + generator and aggregates per-case metrics."""

    def __init__(
        self,
        retriever: RetrieverLike,
        generator: GeneratorLike,
        *,
        top_k: int = 5,
        distance_threshold: float | None = None,
        tenant_id: str = "default",
        notes: str = "",
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._top_k = top_k
        self._distance_threshold = distance_threshold
        self._tenant_id = tenant_id
        self._notes = notes

    async def evaluate(self, dataset: RagEvalDataset) -> RagEvalReport:
        scores: list[RagCaseScore] = []
        for case in dataset.cases:
            request = RetrievalQuery(
                query=case.question,
                top_k=self._top_k,
                distance_threshold=self._distance_threshold,
            )
            retrieval = await self._retriever.retrieve(request, tenant_id=self._tenant_id)
            answer = await self._generator.answer(case.question, retrieval)
            scores.append(score_case(case, retrieval, answer))
        return RagEvalReport(
            dataset_version=dataset.version,
            case_count=len(scores),
            mean_recall=_mean([s.recall for s in scores]),
            mean_groundedness=_mean([s.groundedness for s in scores]),
            abstention_accuracy=_mean([s.abstention_correct for s in scores]),
            pass_rate=_mean([1.0 if s.passed else 0.0 for s in scores]),
            scores=scores,
            notes=self._notes,
        )
