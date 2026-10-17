---
name: agent-development
description: Use when building or changing the multi-agent layer in this repo — LangGraph state/graph, SuperAgent router, worker agents, tool registry, or the provider-independent LLM layer. Load for TASKS.md phases 4 and 6.
---

# Skill: Agent and LangGraph Development

## When to load
Touching `src/ecommerce_support/agents/`, `llm/`, `tools/`, `config/agents.yaml`,
`config/llm.yaml`, or router/worker behavior.

## Framework firewall (strict)
- LangChain/LangGraph imports allowed ONLY in `llm/`, `agents/`, `rag/retrieval.py`.
- Workers are plain Python classes/functions with typed Pydantic I/O in `schemas/`.
  The graph node adapts state → worker → state. Business logic must be unit-testable
  without importing langgraph.

## Router rules
1. Deterministic fast-path first (order/tracking/return/product/account/policy/ticket
   patterns); LLM classification only for ambiguous input; `general`/`clarify` safety net.
2. Bounded execution: max graph iterations from config (`LLM_MAX_GRAPH_ITERATIONS`),
   max 3 routing hops, retry budget ≤ 2 alternative attempts — enforce in graph state,
   record violation as a controlled error, never loop.
3. Typed `AgentState` (intent, selected_agent, auth context, evidence, retry_count,
   resolution_state) — no free-form dicts in state.

## LLM layer rules
- Agents never import provider SDKs or `langchain-*` provider modules — only
  `llm.base.LLMClient` obtained from `llm.factory`.
- Every capability request (stream/tools/structured) is checked against
  `llm/capabilities.py`; unsupported ⇒ `LLMCapabilityError` at call time (fail loudly).
- Retries: max 3, exp backoff + jitter, only for timeout/429/5xx. Normalize provider errors
  to `core/exceptions.py` types. Track usage (tokens/cost) on every result.
- Switching providers must require config only — verify by running tests with
  `LLM_PROVIDER=mock` and at least one real adapter selected in a unit test.

## Tool rules
- Register every tool in `tools/registry.py` with: Pydantic args model, owning agents
  allowlist, audit flag, optional idempotency flag.
- Authorization check inside the tool implementation; least-privilege: a worker can only
  invoke tools its allowlist contains (SEC-008).
- Tools stream nothing; they return typed results. Sensitive payloads get summarized for
  `tool_result` SSE events.

## Definition of done
Router routing tests for every supported intent + bounded-loop test + capability-error test +
tool permission tests, all green with `LLM_PROVIDER=mock`; `make lint typecheck` pass;
`TASKS.md` updated.
