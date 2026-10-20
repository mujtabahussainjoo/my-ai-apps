"""Policy worker: grounded, cited answers from the RAG pipeline (FR-029-FR-034).

Framework-free facade that retrieves policy evidence through the ``search_policies`` tool, then
asks the :class:`~ecommerce_support.rag.generation.GroundedGenerator` to answer strictly from that
evidence. When there is no trusted evidence the worker abstains (FR-034) rather than guessing.
"""

from __future__ import annotations

from ecommerce_support.rag.generation import GroundedGenerator
from ecommerce_support.schemas.agents import AgentResponse, ToolContext
from ecommerce_support.schemas.documents import RetrievalResult
from ecommerce_support.schemas.enums import ToolCallStatus
from ecommerce_support.tools.registry import ToolRegistry

_ERROR_MESSAGE = "I ran into a problem looking that up. Please try again."


class PolicyWorker:
    """Typed facade over policy retrieval + grounded generation for the graph to call."""

    def __init__(self, registry: ToolRegistry, generator: GroundedGenerator) -> None:
        self._registry = registry
        self._generator = generator

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def answer(
        self, query: str, *, context: ToolContext, top_k: int | None = None
    ) -> AgentResponse:
        arguments: dict[str, object] = {"query": query}
        if top_k is not None:
            arguments["top_k"] = top_k
        result = await self._registry.invoke("search_policies", arguments, context=context)
        execution = result.to_execution()
        if result.status is not ToolCallStatus.OK or result.output is None:
            return AgentResponse(
                agent=context.agent, answer=_ERROR_MESSAGE, tool_executions=[execution]
            )

        retrieval = RetrievalResult.model_validate(result.output["retrieval"])
        grounded = await self._generator.answer(query, retrieval)
        return AgentResponse(
            agent=context.agent,
            answer=grounded.answer,
            citations=grounded.citations,
            abstained=grounded.abstained,
            tool_executions=[execution],
        )
