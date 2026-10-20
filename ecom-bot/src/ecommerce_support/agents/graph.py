"""LangGraph orchestration: route → worker → resolve with bounded execution (FR-015-FR-018).

The graph is a thin dispatcher over the framework-free workers. It classifies the intent, selects
the owning agent, invokes that worker through typed tools, and assembles a final :class:`AgentState`.
Execution is strictly bounded: iteration and routing-hop counters are checked on every turn and a
breach produces a controlled error instead of looping. LangGraph is imported only here.
"""

from __future__ import annotations

import re

from langgraph.graph import END, START, StateGraph

from ecommerce_support.agents.resolution import ResolutionAgent
from ecommerce_support.agents.router import Router
from ecommerce_support.agents.workers.account import AccountWorker
from ecommerce_support.agents.workers.order import OrderWorker
from ecommerce_support.agents.workers.policy import PolicyWorker
from ecommerce_support.agents.workers.product import ProductWorker
from ecommerce_support.core.config import AgentsConfig
from ecommerce_support.core.logging import get_logger
from ecommerce_support.integrations.account import AccountAdapter
from ecommerce_support.integrations.commerce import CommerceAdapter
from ecommerce_support.llm.base import LLMClient
from ecommerce_support.rag.generation import GroundedGenerator
from ecommerce_support.rag.retrieval import Retriever
from ecommerce_support.schemas.agents import AgentResponse, AgentState, ToolContext
from ecommerce_support.schemas.enums import (
    AgentName,
    Intent,
    ResolutionAction,
    ResolutionOutcome,
)
from ecommerce_support.tools import (
    create_account_registry,
    create_order_registry,
    create_policy_registry,
    create_product_registry,
)

_logger = get_logger("ecommerce_support.agents.graph")

_SIGN_IN_MESSAGE = "Please sign in and I'll be able to look that up for you."
_CLARIFY_MESSAGE = (
    "Could you share a bit more detail? For example the order number, or the product you mean."
)
_GENERAL_MESSAGE = (
    "Hi! I can help with orders, products, returns, and store policies. What do you need?"
)
_FEEDBACK_MESSAGE = "Thanks for the feedback — I've noted it for the team."
_ESCALATION_MESSAGE = "I can connect you with a human agent. Let me set that up for you."
_BOUNDED_ERROR_MESSAGE = (
    "I couldn't finish that request automatically. Let me connect you with a human agent."
)
_CONFIRM_PROMPT = "Did that resolve your issue?"
_ESCALATE_PROMPT = "I'll pass this to a human agent now — you'll get a ticket reference shortly."

_ORDER_ID_RE = re.compile(r"\b(ord[-_ ]?\d[\w-]*)\b", re.IGNORECASE)
_PRODUCT_ID_RE = re.compile(r"\b((?:prd|sku)[-_ ]?\d[\w-]*)\b", re.IGNORECASE)
_SEARCH_STOPWORDS = frozenset(
    {
        "do",
        "you",
        "have",
        "sell",
        "carry",
        "the",
        "a",
        "an",
        "of",
        "is",
        "are",
        "what",
        "whats",
        "price",
        "pricing",
        "cost",
        "stock",
        "in",
        "out",
        "available",
        "availability",
        "product",
        "products",
        "for",
        "me",
        "please",
        "can",
        "i",
        "buy",
        "and",
        "to",
        "it",
    }
)


def _extract_order_id(message: str) -> str | None:
    match = _ORDER_ID_RE.search(message)
    if match is None:
        return None
    return re.sub(r"[_ ]", "-", match.group(1)).lower()


def _extract_product_id(message: str) -> str | None:
    match = _PRODUCT_ID_RE.search(message)
    if match is None:
        return None
    return re.sub(r"[_ ]", "-", match.group(1)).lower()


def _search_term(message: str) -> str:
    words = [
        word for word in re.findall(r"[a-z0-9]+", message.lower()) if word not in _SEARCH_STOPWORDS
    ]
    return " ".join(words)


def _append(answer: str, prompt: str) -> str:
    text = answer.strip()
    if not text:
        return prompt
    if prompt in text:
        return text
    return f"{text}\n\n{prompt}"


class AgentGraph:
    """Compiles and runs the routing/worker/resolve graph."""

    def __init__(
        self,
        *,
        router: Router,
        order_worker: OrderWorker,
        product_worker: ProductWorker,
        policy_worker: PolicyWorker,
        account_worker: AccountWorker,
        resolution_agent: ResolutionAgent | None = None,
        config: AgentsConfig | None = None,
    ) -> None:
        self._router = router
        self._order = order_worker
        self._product = product_worker
        self._policy = policy_worker
        self._account = account_worker
        self._config = config or AgentsConfig()
        self._resolution = resolution_agent or ResolutionAgent(self._config)
        self._compiled = self._build()

    @property
    def config(self) -> AgentsConfig:
        return self._config

    # -- graph construction ------------------------------------------------

    def _build(self) -> object:
        graph: StateGraph[AgentState] = StateGraph(AgentState)
        graph.add_node("route", self._route_node)
        graph.add_node("dispatch", self._dispatch_node)
        graph.add_node("resolve", self._resolve_node)
        graph.add_edge(START, "route")
        graph.add_conditional_edges(
            "route", self._after_route, {"dispatch": "dispatch", "end": END}
        )
        graph.add_edge("dispatch", "resolve")
        graph.add_conditional_edges(
            "resolve", self._after_resolve, {"dispatch": "dispatch", "end": END}
        )
        return graph.compile()

    # -- nodes -------------------------------------------------------------

    async def _route_node(self, state: AgentState) -> dict[str, object]:
        if state.iterations >= self._config.max_graph_iterations:
            return self._bounded("max_iterations_exceeded")
        if state.hop_count >= self._config.max_routing_hops:
            return self._bounded("max_routing_hops_exceeded")

        decision = await self._router.route(state.message)
        return {
            "intent": decision.intent,
            "selected_agent": decision.agent,
            "requires_auth": decision.requires_auth,
            "router_reason": decision.reason,
            "iterations": state.iterations + 1,
            "hop_count": state.hop_count + 1,
        }

    def _after_route(self, state: AgentState) -> str:
        return "end" if state.error else "dispatch"

    async def _dispatch_node(self, state: AgentState) -> dict[str, object]:
        if state.requires_auth and not state.user_id:
            return self._from_response(
                AgentResponse(
                    agent=state.selected_agent or AgentName.GENERAL, answer=_SIGN_IN_MESSAGE
                )
            )

        context = ToolContext(
            agent=state.selected_agent or AgentName.GENERAL,
            user_id=state.user_id,
            conversation_id=state.conversation_id,
            tenant_id=state.tenant_id,
            request_id=state.request_id,
        )
        try:
            response = await self._run_worker(state, context)
        except Exception as exc:  # a worker failure must not crash the turn
            _logger.warning(
                "agent.dispatch_failed", intent=str(state.intent), error=type(exc).__name__
            )
            return self._bounded("worker_failed")
        return self._from_response(response)

    async def _resolve_node(self, state: AgentState) -> dict[str, object]:
        # Bounded-execution failures are terminal-ish: ask for a human instead of retrying forever.
        if state.error is not None and state.error.startswith("max_"):
            return {
                "resolution_action": ResolutionAction.ESCALATE,
                "resolution_state": ResolutionOutcome.UNRESOLVED,
                "escalation_requested": True,
                "answer": state.answer or _BOUNDED_ERROR_MESSAGE,
            }

        # The customer explicitly asked for a human: escalate without a pointless retry.
        if state.selected_agent is AgentName.ESCALATION:
            return {
                "resolution_action": ResolutionAction.ESCALATE,
                "resolution_state": ResolutionOutcome.UNRESOLVED,
                "escalation_requested": True,
            }

        # A clarification question already asks the customer for more input.
        if state.needs_clarification:
            return {"resolution_action": ResolutionAction.AWAIT_CUSTOMER}

        decision = self._resolution.assess(state)
        if decision.action is ResolutionAction.RESOLVED:
            return {
                "resolution_action": ResolutionAction.RESOLVED,
                "resolution_state": ResolutionOutcome.RESOLVED,
            }
        if decision.action is ResolutionAction.RETRY:
            return {
                "resolution_action": ResolutionAction.RETRY,
                "retry_count": state.retry_count + 1,
                "selected_agent": decision.retry_agent,
                "requires_auth": False,
                "answer": None,
                "needs_clarification": False,
                "abstained": False,
                "error": None,
                "attempts": [*state.attempts, decision.reason],
            }
        if decision.action is ResolutionAction.AWAIT_CUSTOMER:
            return {
                "resolution_action": ResolutionAction.AWAIT_CUSTOMER,
                "answer": _append(state.answer or _CLARIFY_MESSAGE, _CONFIRM_PROMPT),
            }
        # Escalate (FR-048): preserve the answer and offer the human hand-off.
        return {
            "resolution_action": ResolutionAction.ESCALATE,
            "resolution_state": ResolutionOutcome.UNRESOLVED,
            "escalation_requested": True,
            "answer": _append(state.answer or "", _ESCALATE_PROMPT),
        }

    def _after_resolve(self, state: AgentState) -> str:
        if state.error is not None and state.error.startswith("max_"):
            return "end"
        if (
            state.resolution_action is ResolutionAction.RETRY
            and state.retry_count <= self._config.max_retry_attempts
        ):
            return "dispatch"
        return "end"

    # -- worker dispatch ---------------------------------------------------

    async def _run_worker(self, state: AgentState, context: ToolContext) -> AgentResponse:
        agent = state.selected_agent
        intent = state.intent

        if agent is AgentName.ORDER:
            order_id = _extract_order_id(state.message)
            if order_id is not None:
                return await self._order.get_order(order_id, context=context)
            return await self._order.list_orders(context=context)

        if agent is AgentName.PRODUCT:
            product_id = _extract_product_id(state.message)
            lowered = state.message.lower()
            if product_id is not None and any(
                word in lowered for word in ("stock", "available", "availability", "in stock")
            ):
                return await self._product.check_stock(product_id, context=context)
            if product_id is not None:
                return await self._product.get_product(product_id, context=context)
            return await self._product.search(
                query=_search_term(state.message) or None, context=context
            )

        if agent is AgentName.POLICY:
            return await self._policy.answer(state.message, context=context)

        if agent is AgentName.ACCOUNT:
            if "order" in state.message.lower():
                return await self._account.get_summary(context=context)
            return await self._account.get_profile(context=context)

        if intent is Intent.FEEDBACK:
            return AgentResponse(agent=context.agent, answer=_FEEDBACK_MESSAGE)
        if intent is Intent.ESCALATION:
            return AgentResponse(agent=context.agent, answer=_ESCALATION_MESSAGE)
        if intent is Intent.GENERAL:
            return AgentResponse(agent=context.agent, answer=_GENERAL_MESSAGE)
        return AgentResponse(agent=context.agent, answer=_CLARIFY_MESSAGE, needs_clarification=True)

    # -- helpers -----------------------------------------------------------

    def _from_response(self, response: AgentResponse) -> dict[str, object]:
        return {
            "selected_agent": response.agent,
            "answer": response.answer,
            "evidence": response.citations,
            "tool_executions": response.tool_executions,
            "needs_clarification": response.needs_clarification,
            "abstained": response.abstained,
        }

    def _bounded(self, reason: str) -> dict[str, object]:
        return {
            "error": reason,
            "answer": _BOUNDED_ERROR_MESSAGE,
            "attempts": [reason],
        }

    # -- execution ---------------------------------------------------------

    async def ainvoke(self, state: AgentState) -> AgentState:
        """Run one turn through the graph and return the completed state."""
        recursion_limit = self._config.max_graph_iterations * 3 + 5
        result = await self._compiled.ainvoke(  # type: ignore[attr-defined]
            state, config={"recursion_limit": max(10, recursion_limit)}
        )
        return AgentState.model_validate(result)


def create_agent_graph(
    *,
    commerce: CommerceAdapter,
    account: AccountAdapter,
    retriever: Retriever,
    generator: GroundedGenerator,
    router_client: LLMClient | None = None,
    config: AgentsConfig | None = None,
    enable_llm_router: bool | None = None,
) -> AgentGraph:
    """Wire the router, workers, tools, and graph from concrete adapters.

    A convenience for the API/service layer (and tests). ``enable_llm_router`` defaults to the
    config value; the LLM fallback is only used when a ``router_client`` is supplied.
    """
    cfg = config or AgentsConfig()
    if enable_llm_router is None:
        enable_llm_router = cfg.enable_llm_router
    return AgentGraph(
        router=Router(router_client, enable_llm=enable_llm_router),
        order_worker=OrderWorker(create_order_registry(commerce)),
        product_worker=ProductWorker(create_product_registry(commerce)),
        policy_worker=PolicyWorker(create_policy_registry(retriever), generator),
        account_worker=AccountWorker(create_account_registry(account)),
        resolution_agent=ResolutionAgent(cfg),
        config=cfg,
    )
