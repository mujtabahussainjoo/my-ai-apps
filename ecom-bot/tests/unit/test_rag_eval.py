"""Unit tests for the RAG evaluation harness (TASK-021, FR-055)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecommerce_support.core.exceptions import ConfigurationError
from ecommerce_support.evaluation.rag import (
    RagEvaluator,
    load_eval_dataset,
    render_report,
    score_case,
)
from ecommerce_support.schemas.agents import SourceCitation
from ecommerce_support.schemas.documents import (
    DocumentChunk,
    GroundedAnswer,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)
from ecommerce_support.schemas.eval import (
    RagCaseScore,
    RagEvalCase,
    RagEvalDataset,
    RagEvalReport,
)


def _hit(content: str, title: str = "Returns Policy", index: int = 0) -> RetrievalHit:
    return RetrievalHit(
        chunk=DocumentChunk(
            id=f"c{index}",
            document_id="d1",
            version=1,
            chunk_index=index,
            content=content,
            content_hash=f"h{index}",
        ),
        document_title=title,
        score=0.9,
    )


def _citation() -> SourceCitation:
    return SourceCitation(
        document_id="d1", chunk_id="c0", document_title="Returns Policy", score=0.9
    )


def _answer(*, abstained: bool = False, citations: bool = True) -> GroundedAnswer:
    return GroundedAnswer(
        query="q",
        answer="Refunds within thirty days." if not abstained else "I don't know.",
        citations=[_citation()] if citations and not abstained else [],
        abstained=abstained,
        reason="" if not abstained else "no_evidence",
    )


class TestLoadDataset:
    def test_loads_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "ds.yaml"
        path.write_text(
            "version: v1\ncases:\n  - id: c1\n    question: hi?\n    expected_documents: [Returns Policy]\n"
        )
        dataset = load_eval_dataset(path)
        assert dataset.version == "v1"
        assert dataset.cases[0].id == "c1"

    def test_loads_json(self, tmp_path: Path) -> None:
        path = tmp_path / "ds.json"
        path.write_text(json.dumps({"version": "v2", "cases": [{"id": "a", "question": "q"}]}))
        dataset = load_eval_dataset(path)
        assert dataset.version == "v2"

    def test_missing_file_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError):
            load_eval_dataset(tmp_path / "nope.yaml")

    def test_non_mapping_fails_loudly(self, tmp_path: Path) -> None:
        path = tmp_path / "ds.yaml"
        path.write_text("- just\n- a\n- list\n")
        with pytest.raises(ConfigurationError):
            load_eval_dataset(path)

    def test_invalid_case_fails_loudly(self, tmp_path: Path) -> None:
        path = tmp_path / "ds.yaml"
        path.write_text("version: v1\ncases:\n  - id: ''\n    question: q\n")
        with pytest.raises(ConfigurationError):
            load_eval_dataset(path)


class TestScoreCase:
    def test_perfect_case_passes(self) -> None:
        case = RagEvalCase(
            id="c1",
            question="q",
            expected_documents=["Returns Policy"],
            expected_quote="thirty days",
        )
        score = score_case(
            case, RetrievalResult(query="q", hits=[_hit("Refunds within thirty days.")]), _answer()
        )
        assert score.recall == 1.0
        assert score.groundedness == 1.0
        assert score.abstention_correct == 1.0
        assert score.passed is True
        assert score.citation_count == 1

    def test_missing_document_lowers_recall(self) -> None:
        case = RagEvalCase(id="c1", question="q", expected_documents=["Shipping Policy"])
        score = score_case(case, RetrievalResult(query="q", hits=[_hit("x")]), _answer())
        assert score.recall == 0.0
        assert score.passed is False

    def test_missing_quote_fails(self) -> None:
        case = RagEvalCase(id="c1", question="q", expected_quote="ninety days")
        score = score_case(case, RetrievalResult(query="q", hits=[_hit("thirty days")]), _answer())
        assert score.passed is False

    def test_abstention_case_passes_when_abstained(self) -> None:
        case = RagEvalCase(id="c1", question="q", should_abstain=True)
        score = score_case(case, RetrievalResult(query="q", hits=[]), _answer(abstained=True))
        assert score.recall == 1.0
        assert score.groundedness == 1.0
        assert score.passed is True

    def test_abstention_case_fails_when_answered(self) -> None:
        case = RagEvalCase(id="c1", question="q", should_abstain=True)
        score = score_case(case, RetrievalResult(query="q", hits=[_hit("x")]), _answer())
        assert score.groundedness == 0.0
        assert score.abstention_correct == 0.0
        assert score.passed is False

    def test_uncited_answer_is_not_grounded(self) -> None:
        case = RagEvalCase(id="c1", question="q")
        score = score_case(
            case, RetrievalResult(query="q", hits=[_hit("x")]), _answer(citations=False)
        )
        assert score.groundedness == 0.0


class _FakeRetriever:
    def __init__(self, results: dict[str, RetrievalResult]) -> None:
        self._results = results
        self.requests: list[RetrievalQuery] = []

    async def retrieve(
        self, query: str | RetrievalQuery, *, tenant_id: str = "default"
    ) -> RetrievalResult:
        request = query if isinstance(query, RetrievalQuery) else RetrievalQuery(query=query)
        self.requests.append(request)
        return self._results[request.query]


class _FakeGenerator:
    def __init__(self, answers: dict[str, GroundedAnswer]) -> None:
        self._answers = answers

    async def answer(self, query: str, retrieval: RetrievalResult) -> GroundedAnswer:
        return self._answers[query]


class TestRagEvaluator:
    async def test_aggregates_metrics(self) -> None:
        dataset = RagEvalDataset(
            version="v1",
            cases=[
                RagEvalCase(id="hit", question="q1", expected_documents=["Returns Policy"]),
                RagEvalCase(id="abstain", question="q2", should_abstain=True),
            ],
        )
        retriever = _FakeRetriever(
            {
                "q1": RetrievalResult(query="q1", hits=[_hit("thirty days")]),
                "q2": RetrievalResult(query="q2", hits=[]),
            }
        )
        generator = _FakeGenerator({"q1": _answer(), "q2": _answer(abstained=True)})
        report = await RagEvaluator(retriever, generator, top_k=3, notes="n").evaluate(dataset)
        assert report.case_count == 2
        assert report.mean_recall == 1.0
        assert report.mean_groundedness == 1.0
        assert report.abstention_accuracy == 1.0
        assert report.pass_rate == 1.0
        assert report.notes == "n"
        assert retriever.requests[0].top_k == 3

    async def test_render_report_lists_cases(self) -> None:
        report = RagEvalReport(
            dataset_version="v1",
            case_count=1,
            mean_recall=1.0,
            mean_groundedness=1.0,
            abstention_accuracy=1.0,
            pass_rate=1.0,
            scores=[
                RagCaseScore(
                    case_id="c1",
                    recall=1.0,
                    groundedness=1.0,
                    abstention_correct=1.0,
                    citation_count=1,
                    abstained=False,
                    passed=True,
                )
            ],
            notes="n",
        )
        text = render_report(report)
        assert "c1" in text
        assert "PASS" in text
        assert "note: n" in text
