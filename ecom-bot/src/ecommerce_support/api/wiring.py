"""Composition root: build request-scoped services from shared, stateless collaborators.

Keeps provider/client construction (LLM, embeddings, ticketing) out of route handlers and lets
tests override a single dependency. Session-bound adapters/graphs are rebuilt per request because
they share the request's transaction; stateless clients are cached for the process lifetime.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.agents import EscalationAgent, create_agent_graph
from ecommerce_support.core.config import Settings, get_settings
from ecommerce_support.db.repositories import ConversationRepository, ToolExecutionRepository
from ecommerce_support.integrations.sql_account import SqlAccountAdapter
from ecommerce_support.integrations.sql_commerce import SqlCommerceAdapter
from ecommerce_support.integrations.ticketing import TicketingAdapter, create_ticketing_adapter
from ecommerce_support.llm.base import LLMClient
from ecommerce_support.llm.factory import create_llm_client
from ecommerce_support.rag.embeddings.base import EmbeddingProvider
from ecommerce_support.rag.embeddings.factory import create_embedding_provider
from ecommerce_support.rag.generation import create_grounded_generator
from ecommerce_support.rag.retrieval import create_retriever
from ecommerce_support.services import ChatService, TicketService
from ecommerce_support.services.conversations import ConversationService
from ecommerce_support.services.documents import DocumentService


class AppWiring:
    """Builds and caches the collaborators needed by the API layer."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._generation_client: LLMClient | None = None
        self._router_client: LLMClient | None = None
        self._embedder: EmbeddingProvider | None = None
        self._ticketing: TicketingAdapter | None = None

    # -- cached, stateless collaborators -----------------------------------

    @property
    def generation_client(self) -> LLMClient:
        if self._generation_client is None:
            self._generation_client = create_llm_client(self.settings.llm, role="generation")
        return self._generation_client

    @property
    def router_client(self) -> LLMClient | None:
        if self._router_client is None:
            self._router_client = create_llm_client(self.settings.llm, role="router")
        return self._router_client

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = create_embedding_provider(self.settings.llm)
        return self._embedder

    @property
    def ticketing(self) -> TicketingAdapter:
        if self._ticketing is None:
            self._ticketing = create_ticketing_adapter(
                self.settings.integrations.ticketing_provider,
                config=self.settings.integrations,
            )
        return self._ticketing

    # -- request-scoped services -------------------------------------------

    def build_chat_service(self, session: AsyncSession) -> ChatService:
        graph = create_agent_graph(
            commerce=SqlCommerceAdapter(session),
            account=SqlAccountAdapter(session),
            retriever=create_retriever(session, self.embedder, self.settings.rag),
            generator=create_grounded_generator(
                self.generation_client, self.settings.rag, self.settings.guardrails
            ),
            router_client=self.router_client,
            config=self.settings.agents,
        )
        return ChatService(
            agents=graph,
            conversations=ConversationRepository(session),
            escalations=EscalationAgent(),
            tickets=self.build_ticket_service(session),
            tool_executions=ToolExecutionRepository(session),
            guardrails=self.settings.guardrails,
            limits=self.settings.limits,
            commit=session.commit,
        )

    def build_ticket_service(self, session: AsyncSession) -> TicketService:
        return TicketService.from_session(session, self.ticketing)

    def build_conversation_service(self, session: AsyncSession) -> ConversationService:
        return ConversationService(
            ConversationRepository(session), ToolExecutionRepository(session)
        )

    def build_document_service(self, session: AsyncSession) -> DocumentService:
        return DocumentService(session, embedder=self.embedder)


__all__ = ["AppWiring"]
