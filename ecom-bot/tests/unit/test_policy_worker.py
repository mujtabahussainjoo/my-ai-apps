"""Unit tests for the policy worker: grounded retrieval + citations + abstention (TASK-025)."""

from __future__ import annotations

import pytest

from ecommerce_support.agents import PolicyWorker
from ecommerce_support.core.exceptions import AuthorizationError
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.rag.generation import ABSTAIN_MESSAGE, GroundedGenerator
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.documents import (
    DocumentChunk,
    RetrievalHit,
    RetrievalResult,
)
from ecommerce_support.schemas.enums import AgentName, ToolCallStatus
from ecommerce_support.tools import create_policy_registry


class _FakeRetriever:
    """Returns a fixed retrieval result and records the tenant it was asked for."""

    def __init__(self, result: RetrievalResult) -> None:
        self._result = result
        self.tenants: list[str] = []

    async def retrieve(self, query: object, *, tenant_id: str = "default") -> RetrievalResult:
        self.tenants.append(tenant_id)
        return self._result


def _hit(content: str, index: int = 0) -> RetrievalHit:
    return RetrievalHit(
        chunk=DocumentChunk(
            id=f"chunk-{index}",
            document_id="doc-1",
            version=1,
            chunk_index=index,
            content=content,
            content_hash=f"hash-{index}",
            section_title="Returns",
        ),
        document_title="Returns Policy",
        score=0.9,
    )


def _ctx(agent: AgentName = AgentName.POLICY, tenant_id: str = "default") -> ToolContext:
    return ToolContext(agent=agent, tenant_id=tenant_id, conversation_id="conv-1")


class TestPolicyWorker:
    async def test_answers_with_citations(self) -> None:
        retriever = _FakeRetriever(
            RetrievalResult(query="q", hits=[_hit("Returns accepted within 30 days.")])
        )
        client = MockLLMClient(completions=["Returns are accepted within 30 days [1]."])
        worker = PolicyWorker(create_policy_registry(retriever), GroundedGenerator(client))

        response = await worker.answer("What is the return window?", context=_ctx())

        assert response.agent is AgentName.POLICY
        assert response.abstained is False
        assert len(response.citations) == 1
        assert response.citations[0].document_id == "doc-1"
        assert response.citations[0].section_title == "Returns"
        assert response.tool_executions[0].status is ToolCallStatus.OK

    async def test_abstains_without_evidence(self) -> None:
        retriever = _FakeRetriever(RetrievalResult(query="q", hits=[], abstained=True))
        client = MockLLMClient()
        worker = PolicyWorker(create_policy_registry(retriever), GroundedGenerator(client))

        response = await worker.answer("Unknown question", context=_ctx())

        assert response.abstained is True
        assert response.citations == []
        assert response.answer == ABSTAIN_MESSAGE
        assert client.requests == []

    async def test_tenant_scoping_is_forwarded(self) -> None:
        retriever = _FakeRetriever(RetrievalResult(query="q", hits=[_hit("Policy text.")]))
        worker = PolicyWorker(
            create_policy_registry(retriever),
            GroundedGenerator(MockLLMClient(completions=["ok [1]"])),
        )
        await worker.answer("q", context=_ctx(tenant_id="tenant-x"))
        assert retriever.tenants == ["tenant-x"]

    async def test_only_policy_agent_may_retrieve(self) -> None:
        retriever = _FakeRetriever(RetrievalResult(query="q", hits=[]))
        registry = create_policy_registry(retriever)
        with pytest.raises(AuthorizationError):
            await registry.invoke(
                "search_policies", {"query": "q"}, context=_ctx(agent=AgentName.ORDER)
            )
