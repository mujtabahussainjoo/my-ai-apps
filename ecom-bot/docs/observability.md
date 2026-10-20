# Observability: tracing, metrics, and operational logs

Operational visibility for the support bot: correlation ids across every layer, a dependency-free
metrics registry exposed over Prometheus, optional external tracing (off by default), and
structured logs that never contain prompts, secrets, or PII.

Requirements: FR-054 (trace ids end-to-end), FR-055 (baseline metrics), FR-056 (no
chain-of-thought/secrets/PII in logs), FR-057 (external tracing optional, off by default),
INT-006 (LangSmith/OTel export), NFR-002 (first-token latency), SEC-005/SEC-010 (PII
minimization + audit redaction).

## Correlation ids (FR-054)

| Layer | Source | Notes |
| --- | --- | --- |
| HTTP | `RequestContextMiddleware` | Generates `X-Request-ID` (`req_…`) if absent, echoes it, also emits `X-Process-Time` (NFR-002) |
| Service → graph | `request_context(...)` | Binds `request_id` + `conversation_id` into `contextvars` |
| Graph nodes/tools/DB | `bind_conversation_id(...)` | `ChatService._run_turn` binds the conversation id so deep logs attach it without extra params |

`TraceContext.current()` snapshots the active ids. The same `request_id`/`conversation_id` appear on
every log line for a turn, from HTTP ingress through tool calls to persistence (FR-054).

## Metrics (FR-055)

`core/metrics.py` holds a thread-safe, in-process `Metrics` registry (no Prometheus client
dependency) exposed by `GET /metrics` in Prometheus text format.

| Metric | Type | Labels | Source |
| --- | --- | --- | --- |
| `chat_turns_total` | counter | `outcome` (`answered`/`refused`/`escalated`/`clarify`/`error`) | `ChatService` |
| `chat_latency_seconds` | histogram | — | `ChatService` (NFR-002 first-token/latency) |
| `tool_calls_total` | counter | `tool`, `status` (`ok`/`denied`/`unauthenticated`/`invalid`/`error`) | `ToolRegistry` |
| `escalations_total` | counter | `result` (`created`/`reused`/`failed`) | `TicketService` |
| `feedback_total` | counter | `rating` | `FeedbackService` |
| `feedback_rating` | histogram | — | `FeedbackService` |
| `llm_tokens_total` | gauge-like counter | `model`, `kind` (`prompt`/`completion`) | usage tracker |
| `llm_cost_micros_total` | counter | `model` | usage tracker (`llm/usage.py` pricing) |

Histograms expose `count`, `sum`, `min`, `max`, `p50`, `p95` in `Metrics.snapshot()`; the endpoint
renders counters plus histogram `_count`/`_sum`/quantile series. Labels are **low-cardinality and
allow-listed** (`tool`, `status`, `outcome`, `rating`, `model`, `kind`, `result`, `agent`) — never
customer text, ids, or prompts, so metrics can't leak PII (SEC-005).

Baseline quality metrics (retrieval relevance, groundedness, intent routing accuracy, tool
selection accuracy, resolution rate, escalation success rate, ticket duplication rate, latency,
token usage/cost, feedback rating) are reported by the eval harnesses in `evaluation/` and the
`scripts/evaluate_*.py` entrypoints (`make evaluate`, `make evaluate-agents`).

## Evaluation harnesses

- **RAG** — `evaluation/rag.py` + `evals/rag_dataset.yaml`, `scripts/evaluate_rag.py`
  (`make evaluate`): groundedness/relevance/citation/abstention signals.
- **Routing/tool selection** — `evaluation/routing.py` + `evals/routing_dataset.yaml`,
  `scripts/evaluate_agents.py` (`make evaluate-agents`): runs the real agent graph (deterministic
  router + mock LLM + in-memory adapters) and reports `routing_accuracy`, `tool_selection_accuracy`,
  and `pass_rate`; exits non-zero below `--min-routing-accuracy`/`--min-tool-accuracy`.

Both run offline against mock providers — no DB, credentials, or network required.

## Optional external tracing (FR-057, INT-006)

External tracing is **off by default** (`OBSERVABILITY__TRACING_ENABLED=false`). When enabled *and*
an API key is configured, `core/tracing.py::configure_tracing` sets the LangSmith/LangChain
environment variables so LangGraph emits traces; without a key it logs
`tracing.enabled_without_key` and stays off. No tracing SDK is imported by application code, so the
zero-credentials/zero-network test contract holds. OTel export can be layered on the same hook.

## Operationally-safe logs (FR-056, SEC-005, SEC-010)

- Structured logs via `core/logging.py`; every record carries request/conversation correlation.
- `_redact_sensitive` strips secrets/PII from log payloads; guardrail events log **kinds only**
  (`guardrail.output_redacted`), never the matched text.
- Prompts, retrieved evidence, and chain-of-thought are never logged; metrics and traces carry only
  numeric aggregates and allow-listed labels.
- Audit events (`AuditEvent`) record resource ids and event types, not message bodies.
