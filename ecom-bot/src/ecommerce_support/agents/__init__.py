"""Agent layer: router + workers + LangGraph orchestration (Phase 6).

LangChain/LangGraph imports are confined to this package (plus ``llm/`` and ``rag/retrieval.py``).
Workers are plain Python with typed Pydantic I/O and are unit-tested without the framework runtime.
"""

from ecommerce_support.agents.escalation import EscalationAgent
from ecommerce_support.agents.graph import AgentGraph, create_agent_graph
from ecommerce_support.agents.resolution import ResolutionAgent
from ecommerce_support.agents.router import Router, classify_message
from ecommerce_support.agents.workers.account import AccountWorker
from ecommerce_support.agents.workers.order import OrderWorker
from ecommerce_support.agents.workers.policy import PolicyWorker
from ecommerce_support.agents.workers.product import ProductWorker

__all__ = [
    "AccountWorker",
    "AgentGraph",
    "EscalationAgent",
    "OrderWorker",
    "PolicyWorker",
    "ProductWorker",
    "ResolutionAgent",
    "Router",
    "classify_message",
    "create_agent_graph",
]
