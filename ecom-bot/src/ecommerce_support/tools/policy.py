"""Policy search tool: RAG retrieval over policy documents (FR-029-FR-034, FR-039).

Wraps a :class:`~ecommerce_support.rag.retrieval.Retriever` so the policy worker can retrieve
cited evidence through the typed registry (validation + allowlist + audit). The tool only returns
raw retrieval evidence; grounding/generation happens in the worker.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ecommerce_support.rag.retrieval import Retriever
from ecommerce_support.schemas import RetrievalQuery
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName
from ecommerce_support.tools.audit import AuditHook
from ecommerce_support.tools.registry import Tool, ToolRegistry, create_tool_registry

_POLICY_AGENTS = frozenset({AgentName.POLICY})


class SearchPoliciesArgs(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)


class SearchPoliciesTool(Tool[SearchPoliciesArgs]):
    """Retrieve policy evidence for a customer question, scoped to the caller's tenant."""

    name = "search_policies"
    description = "Search policy documents and return cited evidence for a question."
    arguments_model = SearchPoliciesArgs
    allowed_agents = _POLICY_AGENTS

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    async def run(self, arguments: SearchPoliciesArgs, context: ToolContext) -> dict[str, object]:
        query: str | RetrievalQuery = arguments.query
        if arguments.top_k is not None:
            query = RetrievalQuery(query=arguments.query, top_k=arguments.top_k)
        retrieval = await self._retriever.retrieve(query, tenant_id=context.tenant_id)
        return {"retrieval": retrieval.model_dump(mode="json")}

    def summarize(self, result: dict[str, object]) -> str:
        retrieval = result.get("retrieval")
        hits = retrieval.get("hits") if isinstance(retrieval, dict) else None
        count = len(hits) if isinstance(hits, list) else 0
        return f"retrieved {count} policy chunks"


def create_policy_registry(
    retriever: Retriever, *, audit_hook: AuditHook | None = None
) -> ToolRegistry:
    """Build a registry containing the policy search tool bound to ``retriever``."""
    return create_tool_registry([SearchPoliciesTool(retriever)], audit_hook=audit_hook)
