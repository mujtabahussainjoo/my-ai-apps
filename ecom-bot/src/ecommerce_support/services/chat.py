"""Chat use-case: persist a turn, run the agent graph, escalate, and record the outcome.

Framework-free (the graph is injected as an :class:`AgentRunner` protocol). This is the single
place that enforces the conversation contract for a turn:

- creates the conversation on first contact, or rejects an unknown ``conversation_id`` (FR-002);
- persists the customer message and the final assistant answer even when downstream steps fail
  (FR-009);
- runs a prompt-injection guardrail before the graph and refuses unsafe input (FR-032);
- when the graph asks for escalation, dispatches a ticket through
  :class:`~ecommerce_support.services.tickets.TicketService` and reports the reference — or, on
  failure, a truthful message while preserving the escalation (FR-025, ACC-005/006);
- advances the conversation status through the FR-047 state machine.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from typing import Protocol

from ecommerce_support.core.config import GuardrailsConfig, LimitsConfig
from ecommerce_support.core.exceptions import AppError, NotFoundError, TicketCreationError
from ecommerce_support.core.logging import get_logger
from ecommerce_support.core.metrics import record_chat_turn
from ecommerce_support.core.observability import bind_conversation_id
from ecommerce_support.db.repositories import ConversationRepository
from ecommerce_support.guardrails import screen_input, screen_output
from ecommerce_support.schemas import (
    AgentState,
    ChatRequest,
    ChatResponse,
    Conversation,
    ErrorEvent,
    MessageEndEvent,
    MessageStartEvent,
    SourceEvent,
    StreamEventBase,
    TicketCreatedEvent,
    TicketEscalationResult,
    TicketRequest,
    TokenEvent,
    ToolExecution,
    ToolResultEvent,
    ToolStartEvent,
)
from ecommerce_support.schemas.enums import (
    AgentName,
    ConversationStatus,
    MessageRole,
    ResolutionAction,
    ToolCallStatus,
)
from ecommerce_support.services.tickets import TicketService
from ecommerce_support.workflows.lifecycle import can_transition

REFUSAL_MESSAGE = (
    "I can't help with that request. If you need help with an order, a product, or a store "
    "policy, tell me what you need and I'll take a look."
)
FALLBACK_MESSAGE = (
    "Sorry, I couldn't produce an answer just now. Could you rephrase, or share more detail?"
)
_TICKET_FAILURE_MESSAGE = (
    "I couldn't create a support ticket just now, but your request is still with our team. "
    "Please try again in a moment."
)
_ERROR_MESSAGE = (
    "Sorry — something went wrong while handling your request. Please try again in a moment."
)
_INTERRUPTED_MESSAGE = "Your request was interrupted before it finished. Please send it again."

_TOKEN_RE = re.compile(r"\S+\s*")

_log = get_logger(__name__)


class AgentRunner(Protocol):
    """Runs one turn through the agent graph (implemented by ``agents.AgentGraph``)."""

    async def ainvoke(self, state: AgentState) -> AgentState: ...


class EscalationBuilder(Protocol):
    """Builds a ticket request from the workflow state (``agents.EscalationAgent``)."""

    def build_request(self, state: AgentState) -> TicketRequest: ...


class CommitHook(Protocol):
    """Commits the unit of work (used to persist partial state on disconnect, FR-013)."""

    async def __call__(self) -> None: ...


class ToolExecutionRecorder(Protocol):
    """Persists a tool invocation audit row (``db.ToolExecutionRepository``; FR-009)."""

    async def record(
        self,
        *,
        conversation_id: str,
        message_id: str | None,
        tool_name: str,
        call_id: str,
        status: ToolCallStatus,
        summary: str = "",
        duration_ms: float | None = None,
    ) -> object: ...


class ChatService:
    """Orchestrates a single chat turn."""

    def __init__(
        self,
        agents: AgentRunner,
        *,
        conversations: ConversationRepository,
        escalations: EscalationBuilder,
        tickets: TicketService | None = None,
        tool_executions: ToolExecutionRecorder | None = None,
        guardrails: GuardrailsConfig | None = None,
        limits: LimitsConfig | None = None,
        commit: CommitHook | None = None,
    ) -> None:
        self._agents = agents
        self._conversations = conversations
        self._escalations = escalations
        self._tickets = tickets
        self._tool_executions = tool_executions
        self._guardrails = guardrails or GuardrailsConfig()
        self._limits = limits or LimitsConfig()
        self._commit = commit

    async def chat(
        self,
        request: ChatRequest,
        *,
        user_id: str | None = None,
        tenant_id: str = "default",
        request_id: str | None = None,
    ) -> ChatResponse:
        """Process one customer turn and return the persisted assistant answer."""
        started = time.perf_counter()
        conversation = await self._load_or_create(request, user_id=user_id, tenant_id=tenant_id)
        await self._conversations.append_message(
            conversation.id, role=MessageRole.USER, content=request.message
        )
        await self._move_status(conversation, ConversationStatus.IN_PROGRESS)

        state = await self._run_turn(
            conversation, request, user_id=user_id, tenant_id=tenant_id, request_id=request_id
        )

        if state is None:  # refused by the prompt-injection guardrail
            answer = REFUSAL_MESSAGE
            escalated = False
        elif state.escalation_requested:
            answer, _ticket = await self._escalate_result(state)
            escalated = True
        else:
            answer = state.answer if state.answer else FALLBACK_MESSAGE
            escalated = False

        answer = self._screen_answer(answer)

        assistant = await self._conversations.append_message(
            conversation.id,
            role=MessageRole.ASSISTANT,
            content=answer,
            agent=state.selected_agent if state else AgentName.GENERAL,
        )
        if state is not None:
            await self._persist_tool_executions(
                conversation.id, assistant.id, state.tool_executions
            )
        if not escalated:
            await self._finalize_status(conversation, state)

        record_chat_turn(
            self._turn_outcome(state, escalated=escalated),
            time.perf_counter() - started,
        )
        return ChatResponse(
            conversation_id=conversation.id,
            message=assistant,
            resolution_state=state.resolution_state if state else None,
            request_id=request_id,
        )

    @staticmethod
    def _turn_outcome(state: AgentState | None, *, escalated: bool) -> str:
        if state is None:
            return "refused"
        if escalated:
            return "escalated"
        if state.needs_clarification:
            return "clarify"
        return "answered"

    async def stream(
        self,
        request: ChatRequest,
        *,
        user_id: str | None = None,
        tenant_id: str = "default",
        request_id: str | None = None,
    ) -> AsyncIterator[StreamEventBase]:
        """Stream a turn as typed lifecycle events (FR-010).

        Emits ``message_start`` → ``tool_start``/``tool_result``/``source`` → ``token`` →
        ``ticket_created`` → ``message_end``. Failures after streaming begins emit ``error``
        followed by a terminal ``message_end`` (FR-012); a client disconnect persists the partial
        state before re-raising (FR-013). Only customer-visible data is emitted (FR-011).
        """
        try:
            conversation = await self._load_or_create(request, user_id=user_id, tenant_id=tenant_id)
        except AppError as exc:
            yield ErrorEvent(
                request_id=request_id,
                conversation_id=request.conversation_id,
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
            )
            yield MessageEndEvent(request_id=request_id, conversation_id=request.conversation_id)
            return

        try:
            async for event in self._stream_turn(
                conversation, request, user_id=user_id, tenant_id=tenant_id, request_id=request_id
            ):
                yield event
        except asyncio.CancelledError:
            await self._persist_interruption(conversation)
            raise

    async def _stream_turn(
        self,
        conversation: Conversation,
        request: ChatRequest,
        *,
        user_id: str | None,
        tenant_id: str,
        request_id: str | None,
    ) -> AsyncIterator[StreamEventBase]:
        cid = conversation.id
        started = time.perf_counter()
        yield MessageStartEvent(conversation_id=cid, request_id=request_id)
        await self._conversations.append_message(
            cid, role=MessageRole.USER, content=request.message
        )
        await self._move_status(conversation, ConversationStatus.IN_PROGRESS)

        try:
            state = await self._run_turn(
                conversation, request, user_id=user_id, tenant_id=tenant_id, request_id=request_id
            )
        except Exception as exc:
            record_chat_turn("error", time.perf_counter() - started)
            async for event in self._stream_failure(conversation, exc, request_id=request_id):
                yield event
            return

        if state is not None:
            async for event in self._state_events(state, cid, request_id):
                yield event

        ticket = None
        if state is None:
            answer = REFUSAL_MESSAGE
        elif state.escalation_requested:
            answer, ticket = await self._escalate_result(state)
        else:
            answer = state.answer if state.answer else FALLBACK_MESSAGE

        answer = self._screen_answer(answer)

        for chunk in _tokenize(answer):
            yield TokenEvent(conversation_id=cid, request_id=request_id, text=chunk)

        if ticket is not None:
            yield TicketCreatedEvent(
                conversation_id=cid,
                request_id=request_id,
                ticket_id=ticket.ticket.id,
                external_id=ticket.ticket.external_id,
                provider=ticket.ticket.provider,
                status=ticket.ticket.status,
                url=ticket.ticket.url,
            )

        assistant = await self._conversations.append_message(
            cid,
            role=MessageRole.ASSISTANT,
            content=answer,
            agent=state.selected_agent if state else AgentName.GENERAL,
        )
        if state is not None:
            await self._persist_tool_executions(cid, assistant.id, state.tool_executions)
        if not (state is not None and state.escalation_requested):
            await self._finalize_status(conversation, state)
        status = await self._current_status(conversation)
        record_chat_turn(
            self._turn_outcome(state, escalated=state is not None and state.escalation_requested),
            time.perf_counter() - started,
        )
        yield MessageEndEvent(
            conversation_id=cid,
            request_id=request_id,
            message_id=assistant.id,
            content=answer,
            resolution_state=state.resolution_state if state else None,
            conversation_status=status,
        )

    async def _state_events(
        self, state: AgentState, conversation_id: str, request_id: str | None
    ) -> AsyncIterator[StreamEventBase]:
        for execution in state.tool_executions:
            yield ToolStartEvent(
                conversation_id=conversation_id,
                request_id=request_id,
                tool=execution.tool_name,
                call_id=execution.call_id,
            )
            yield ToolResultEvent(
                conversation_id=conversation_id,
                request_id=request_id,
                tool=execution.tool_name,
                call_id=execution.call_id,
                status=execution.status.value,
                summary=execution.summary,
            )
        if state.evidence:
            yield SourceEvent(
                conversation_id=conversation_id,
                request_id=request_id,
                citations=state.evidence,
            )

    async def _stream_failure(
        self, conversation: Conversation, exc: BaseException, *, request_id: str | None
    ) -> AsyncIterator[StreamEventBase]:
        if isinstance(exc, AppError):
            code, message, retryable = exc.code, exc.message, exc.retryable
        else:
            code, message, retryable = "internal_error", _ERROR_MESSAGE, True
        assistant = await self._conversations.append_message(
            conversation.id,
            role=MessageRole.ASSISTANT,
            content=_ERROR_MESSAGE,
            agent=AgentName.GENERAL,
        )
        await self._move_status(conversation, ConversationStatus.ERROR)
        yield ErrorEvent(
            conversation_id=conversation.id,
            request_id=request_id,
            code=code,
            message=message,
            retryable=retryable,
        )
        yield MessageEndEvent(
            conversation_id=conversation.id,
            request_id=request_id,
            message_id=assistant.id,
            content=_ERROR_MESSAGE,
            conversation_status=ConversationStatus.ERROR,
        )

    async def _persist_interruption(self, conversation: Conversation) -> None:
        """Best-effort persistence of partial state on client disconnect (FR-013)."""
        try:
            await self._conversations.append_message(
                conversation.id,
                role=MessageRole.ASSISTANT,
                content=_INTERRUPTED_MESSAGE,
                agent=AgentName.GENERAL,
            )
            await self._move_status(conversation, ConversationStatus.ERROR)
            if self._commit is not None:
                await self._commit()
        except Exception:
            return

    async def _current_status(self, conversation: Conversation) -> ConversationStatus:
        fresh = await self._conversations.get(conversation.id)
        return fresh.status if fresh is not None else conversation.status

    async def _persist_tool_executions(
        self, conversation_id: str, message_id: str, executions: list[ToolExecution]
    ) -> None:
        """Best-effort audit of the turn's tool activity, linked to the assistant message."""
        if self._tool_executions is None:
            return
        for execution in executions:
            try:
                await self._tool_executions.record(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    tool_name=execution.tool_name,
                    call_id=execution.call_id,
                    status=execution.status,
                    summary=execution.summary,
                    duration_ms=execution.duration_ms,
                )
            except Exception:
                return

    # -- internals ---------------------------------------------------------

    async def _load_or_create(
        self, request: ChatRequest, *, user_id: str | None, tenant_id: str
    ) -> Conversation:
        if request.conversation_id is None:
            return await self._conversations.create(user_id=user_id, tenant_id=tenant_id)
        conversation = await self._conversations.get(request.conversation_id)
        # Ownership (SEC-002): a caller may only continue a conversation they own. A mismatch is
        # indistinguishable from a missing conversation so existence is not leaked.
        if conversation is None or conversation.user_id != user_id:
            raise NotFoundError(
                "Conversation not found.",
                details={"conversation_id": request.conversation_id},
            )
        return conversation

    async def _run_turn(
        self,
        conversation: Conversation,
        request: ChatRequest,
        *,
        user_id: str | None,
        tenant_id: str,
        request_id: str | None,
    ) -> AgentState | None:
        """Run guardrails + the graph; ``None`` when input is refused by the guardrail."""
        decision = screen_input(
            request.message,
            max_chars=self._limits.max_message_chars,
            enabled=self._guardrails.enabled,
            injection_action=self._guardrails.prompt_injection_action,
            injection_threshold=self._guardrails.max_prompt_injection_score,
        )
        if decision.blocked:
            _log.warning(
                "guardrail.input_blocked",
                code=decision.code,
                matches=decision.matches,
                conversation_id=conversation.id,
            )
            return None
        state = AgentState(
            conversation_id=conversation.id,
            user_id=user_id,
            tenant_id=tenant_id,
            request_id=request_id,
            message=request.message,
        )
        with bind_conversation_id(conversation.id):
            return await self._agents.ainvoke(state)

    def _screen_answer(self, answer: str) -> str:
        """Redact secrets/PII from an outbound answer before it is persisted or streamed."""
        decision = screen_output(answer, enabled=self._guardrails.enabled)
        if decision.redacted and decision.text is not None:
            _log.warning("guardrail.output_redacted", matches=decision.matches)
            return decision.text
        return answer

    async def _escalate_result(
        self, state: AgentState
    ) -> tuple[str, TicketEscalationResult | None]:
        """Create a ticket for an unresolved state; return the answer and any created ticket."""
        prefix = state.answer or FALLBACK_MESSAGE
        if self._tickets is None:
            return prefix, None
        request = self._escalations.build_request(state)
        try:
            result = await self._tickets.escalate(request)
        except TicketCreationError:
            return f"{prefix}\n\n{_TICKET_FAILURE_MESSAGE}", None
        reference = result.ticket.external_id or result.ticket.id
        message = f"I've created a support ticket for you (reference {reference})."
        if result.ticket.url:
            message = f"{message} You can track it at {result.ticket.url}"
        return f"{prefix}\n\n{message}", result

    async def _finalize_status(self, conversation: Conversation, state: AgentState | None) -> None:
        if state is None:
            await self._move_status(conversation, ConversationStatus.AWAITING_CUSTOMER)
            return
        if state.needs_clarification:
            await self._move_status(conversation, ConversationStatus.AWAITING_CUSTOMER)
            return
        action = state.resolution_action
        if action is ResolutionAction.RESOLVED:
            await self._move_status(conversation, ConversationStatus.RESOLVED)
        elif action is ResolutionAction.AWAIT_CUSTOMER:
            await self._move_status(conversation, ConversationStatus.AWAITING_CUSTOMER)
        elif action is ResolutionAction.ESCALATE:
            await self._move_status(conversation, ConversationStatus.ESCALATION_PENDING)
        else:
            await self._move_status(conversation, ConversationStatus.IN_PROGRESS)

    async def _move_status(self, conversation: Conversation, target: ConversationStatus) -> None:
        current = conversation.status
        if current is target:
            return
        if can_transition(current, target):
            await self._conversations.update_status(conversation.id, target)
            return
        if can_transition(current, ConversationStatus.IN_PROGRESS) and can_transition(
            ConversationStatus.IN_PROGRESS, target
        ):
            await self._conversations.update_status(conversation.id, ConversationStatus.IN_PROGRESS)
            await self._conversations.update_status(conversation.id, target)


__all__ = [
    "AgentRunner",
    "ChatService",
    "CommitHook",
    "EscalationBuilder",
    "ToolExecutionRecorder",
]


def _tokenize(text: str) -> list[str]:
    """Split an answer into whitespace-preserving chunks for ``token`` events."""
    chunks = _TOKEN_RE.findall(text)
    return chunks or ([text] if text else [])
