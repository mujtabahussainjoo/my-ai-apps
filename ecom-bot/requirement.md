# Requirements Specification — E-commerce AI Support Assistant

| Field | Value |
| --- | --- |
| Document ID | REQ-001 |
| Version | 1.0 |
| Status | Draft — approved for planning (TASK-002) |
| Date | 2026-10-16 |
| Owner | Engineering |
| Related | `TASKS.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md` |

---

## 1. Purpose and Scope

This document specifies the requirements for a production-oriented AI support chatbot for an
e-commerce store. The system answers customer questions about orders, products, accounts,
shipping, returns, refunds, store policies, and general support; streams responses over HTTP;
collects feedback; and escalates unresolved issues to Jira or ServiceNow.

In scope:

- Backend API service (FastAPI), multi-agent orchestration (LangGraph), RAG over store
  policies, provider-independent LLM layer, PostgreSQL + pgvector persistence, mock-first
  commerce and ticketing integrations, guardrails, streaming, tests, and deployment assets.
- Mock e-commerce data with clean adapter interfaces for a future real backend
  (Magento/Adobe Commerce or other).

Out of scope (v1):

- Production Magento/Adobe Commerce connection (interface only; mock adapter ships).
- Real Jira/ServiceNow credentials (adapters implemented, disabled until configured).
- Full-featured frontend (backend first; example SSE client only).
- Voice, email, or multi-channel support.
- Payments, refunds execution, cancellations, or any account-mutating action
  (read-only support + ticket escalation in v1).

## 2. Actors

| Actor | Description |
| --- | --- |
| Guest customer | Unauthenticated website visitor asking public questions (products, policies). |
| Authenticated customer | Customer with an account; may access their own orders/profile. |
| Store administrator | Manages documents, ingestion, evaluation, and protected endpoints. |
| Support agent (human) | Receives and works escalated Jira/ServiceNow tickets. |
| Operator/developer | Runs, observes, evaluates, and deploys the system. |

## 3. Functional Requirements

### 3.1 Conversation and API

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-001 | The system SHALL accept customer messages via `POST /api/v1/chat` and return a streamed response (SSE) with typed events. | Must |
| FR-002 | The system SHALL support multi-turn conversations persisted by `conversation_id`, with full message history retrieval. | Must |
| FR-003 | The system SHALL support a non-streaming JSON mode for simple clients and tests. | Should |
| FR-004 | The system SHALL ask clarifying questions when required information is missing (e.g., missing order number for unauthenticated user). | Must |
| FR-005 | The system SHALL return conversation and request correlation IDs in every response and event. | Must |
| FR-006 | The system SHALL expose `GET /health` (liveness) and `GET /ready` (readiness incl. DB check). | Must |
| FR-007 | The system SHALL expose versioned endpoints under `/api/v1/` with OpenAPI documentation. | Must |
| FR-008 | List endpoints SHALL support pagination (limit/offset or cursor) and stable ordering. | Should |
| FR-009 | The system SHALL persist the final assistant message, tool execution records, and final conversation status even when downstream steps fail. | Must |

### 3.2 Streaming (SSE)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-010 | The stream SHALL emit typed lifecycle events: `message_start`, `token`, `tool_start`, `tool_result`, `source`, `ticket_created`, `error`, `message_end`. | Must |
| FR-011 | Only customer-visible content SHALL be streamed; hidden reasoning/chain-of-thought and raw tool outputs SHALL NOT be emitted. | Must |
| FR-012 | Errors occurring after streaming begins SHALL be reported as an `error` event followed by a terminal `message_end` with status. | Must |
| FR-013 | Client disconnects SHALL cancel in-flight generation and still persist partial state as `ABANDONED`/`ERROR` per policy. | Must |
| FR-014 | The SSE event schema SHALL be documented with example client code. | Must |

### 3.3 SuperAgent / Router

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-015 | A SuperAgent/Router built on LangGraph SHALL classify intent and route to specialized workers. | Must |
| FR-016 | Routing SHALL be deterministic (rule/keyword based) when intent is unambiguous and MAY use LLM classification for ambiguous inputs. | Must |
| FR-017 | The router SHALL enforce bounded execution: maximum graph iterations, no infinite routing loops, per-request step budget. | Must |
| FR-018 | The router SHALL track workflow state (intent, selected agent, auth requirement, retry count, resolution status) in typed graph state. | Must |
| FR-019 | Unknown/unsupported intents SHALL fall back safely to a clarification or general-support path, never a fabricated answer. | Must |

### 3.4 Specialized workers

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-020 | **Order Agent** SHALL retrieve orders, shipment/tracking status, and explain order states; SHALL verify ownership/authorization before returning private data. | Must |
| FR-021 | **Product Agent** SHALL search the catalog and return specifications, prices, and stock from the commerce adapter; SHALL NOT invent prices or stock. | Must |
| FR-022 | **Policy RAG Agent** SHALL retrieve policy/FAQ chunks via pgvector semantic search with metadata filters, produce grounded answers with source citations, and abstain when evidence is insufficient. | Must |
| FR-023 | **Account Agent** SHALL handle authorized profile/account questions with strict ownership checks; SHALL NEVER expose passwords, tokens, or another customer's data. | Must |
| FR-024 | **Resolution Agent** SHALL ask whether the issue is resolved, evaluate evidence sufficiency, and decide retry vs. escalation; SHALL NOT treat answer generation as proof of resolution. | Must |
| FR-025 | **Escalation Agent** SHALL create/retrieve Jira or ServiceNow tickets with redacted, structured summaries and store external ticket ID/URL/status. | Must |
| FR-026 | **Feedback Worker** SHALL record rating (1–5), optional comment, conversation ID, and resolution outcome. | Must |
| FR-027 | Each worker SHALL have typed input/output contracts, a limited tool allowlist, and unit tests. | Must |
| FR-028 | Simple operations SHALL be plain functions/graph nodes, not extra autonomous agents. | Should |

### 3.5 RAG pipeline

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-029 | Ingestion SHALL accept supported document formats (`.md`, `.txt`, `.pdf`, `.html`), validate type/size, extract and normalize text, and record ingestion status/errors. | Must |
| FR-030 | Ingestion SHALL chunk documents with configurable size/overlap, generate embeddings via a configurable provider, and store chunks + metadata + embeddings in PostgreSQL with pgvector. | Must |
| FR-031 | Ingestion SHALL support re-ingestion with document versioning and SHALL avoid duplicate chunks (content hash / source+version dedupe). | Must |
| FR-032 | Retrieval SHALL apply query normalization, embedding, top-k similarity search, metadata filters, configurable relevance threshold, and optional reranking. | Must |
| FR-033 | Generated policy answers SHALL include citations traceable to document + section/chunk. | Must |
| FR-034 | When retrieved evidence is below the relevance threshold, the agent SHALL abstain and route to clarification or escalation instead of answering. | Must |
| FR-035 | Chunk size, overlap, top-k, distance metric, and thresholds SHALL be configurable (`config/rag.yaml`); chosen defaults SHALL be documented with rationale. | Must |
| FR-036 | Changing embedding models SHALL require explicit dimension compatibility validation at startup/ingestion. | Must |
| FR-037 | A small version-controlled evaluation dataset and baseline retrieval/groundedness metrics SHALL exist (`scripts/evaluate_rag.py`). | Should |

### 3.6 Tools and integrations

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-038 | Tools SHALL be typed (Pydantic-validated), registered in a central registry, and each tool SHALL declare its owning agent/permission scope. | Must |
| FR-039 | Required tools: search products, product details, stock check, get order, track shipment, return eligibility, search policies, collect feedback, create Jira ticket, create ServiceNow incident, get ticket status. | Must |
| FR-040 | Authorization (customer/order ownership) SHALL be enforced in the tool/service layer, never by prompt instruction alone. | Must |
| FR-041 | Commerce backend SHALL sit behind an adapter interface; mock adapter ships first, real Magento/Commerce adapter is a documented extension point. | Must |
| FR-042 | Ticketing SHALL support Jira, ServiceNow, both, or none via configuration without changing agent business logic. | Must |
| FR-043 | Ticket creation SHALL be idempotent (idempotency key persisted) to prevent duplicates across retries. | Must |
| FR-044 | Ticket creation SHALL NEVER be reported as successful unless the external service confirmed it; failures SHALL preserve the escalation request, expose `TICKET_CREATION_FAILED`, and offer retry/human-support fallback. | Must |
| FR-045 | Sensitive or high-impact actions (refunds, cancellations, account changes) SHALL NOT be executable by the agent in v1; requests for them SHALL be routed to escalation. | Must |

### 3.7 Resolution, feedback, and escalation lifecycle

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-046 | After each answer the system SHALL ask the customer whether the issue was resolved. | Must |
| FR-047 | Lifecycle states SHALL follow the documented state machine: `OPEN → IN_PROGRESS → AWAITING_CUSTOMER → RESOLVED`, and when unresolved `→ ESCALATION_PENDING → TICKET_CREATED`, with failure state `TICKET_CREATION_FAILED`. | Must |
| FR-048 | If unresolved, the system SHALL collect remaining problem details, retry with an alternative agent or additional retrieval (bounded), and escalate if still unresolved. | Must |
| FR-049 | Escalation SHALL require customer confirmation when policy demands it before ticket creation. | Should |
| FR-050 | Ticket payloads SHALL include issue summary, relevant messages, authorized order/product references, retrieval sources, steps attempted, expected vs. actual behavior, redacted findings, and priority per documented rules. | Must |
| FR-051 | Ticket payloads SHALL NOT include credentials, payment details, unnecessary PII, or internal reasoning. | Must |
| FR-052 | Feedback records SHALL be queryable by conversation, rating, and outcome for reporting. | Must |
| FR-053 | Ticket status and reference SHALL be retrievable by the customer via API. | Must |

### 3.8 Evaluation and observability

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-054 | Structured logs with trace IDs SHALL correlate API request → graph node → tool call → external call. | Must |
| FR-055 | Baseline metrics SHALL cover: retrieval relevance, answer groundedness, intent routing accuracy, tool selection accuracy, resolution rate, escalation success rate, ticket duplication rate, latency, token usage/estimated cost, feedback rating. | Should |
| FR-056 | Chain-of-thought, secrets, payment info, and unnecessary customer data SHALL NOT be logged. | Must |
| FR-057 | External tracing (LangSmith or equivalent) SHALL be optional and configuration-disabled by default. | Should |

## 4. Non-Functional Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-001 | Python 3.12+, FastAPI, LangGraph, LangChain (where appropriate), Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL + pgvector, HTTPX, SSE, pytest, Ruff, Docker. | Must |
| NFR-002 | First meaningful streamed token p50 < 2.0 s and p95 < 5.0 s with mock/local providers under test load; documented per provider in production. | Should |
| NFR-003 | API request timeout budget with bounded retries (max 3 attempts, exponential backoff + jitter) and per-provider timeout configuration. | Must |
| NFR-004 | Rate limiting per client on chat endpoints (configurable, default e.g. 60 req/min). | Must |
| NFR-005 | Input size limits: max message length (default 4000 chars), max document size (default 10 MB), max chunks per ingest request. | Must |
| NFR-006 | The service SHALL run locally with `docker compose` (or documented equivalent) and pass `make test`/`make lint`/`make typecheck` gates. | Must |
| NFR-007 | Provider-specific code SHALL be isolated behind a common LLM interface; switching Anthropic ↔ OpenAI ↔ Gemini ↔ Ollama ↔ OpenAI-compatible SHALL require configuration only. | Must |
| NFR-008 | All external services must be mockable; the core test suite SHALL run without real credentials or network access to providers. | Must |
| NFR-009 | Dependency versions SHALL be pinned; lockfile committed. | Must |
| NFR-010 | Asynchronous I/O throughout the request path (no blocking calls in event loop). | Must |
| NFR-011 | Graceful shutdown: in-flight requests drained, DB pool closed. | Should |
| NFR-012 | Data retention/deletion: conversations/messages retained per configurable TTL; `DELETE` support for a customer's conversation data. | Should |
| NFR-013 | API responses SHALL never expose stack traces, SQL, or internal prompts. | Must |

## 5. Security and Privacy Requirements

| ID | Requirement |
| --- | --- |
| SEC-001 | JWT-based authentication (or pluggable IdP) for customer identity; admin endpoints require elevated scope. |
| SEC-002 | Ownership checks on orders/accounts in the service layer; cross-customer access SHALL return not-found/forbidden without data leakage. |
| SEC-003 | Prompt-injection defenses: untrusted content (customer messages, retrieved docs, tool outputs) SHALL be delimited/sanitized and never treated as instructions; injection attempts logged as security events. |
| SEC-004 | Output validation: block/refuse requests for secrets, other customers' data, payment data, and high-impact actions. |
| SEC-005 | PII minimization/redaction in logs, traces, tickets, and evaluation datasets. |
| SEC-006 | Secrets only via environment/`.env`; `.env.example` committed; real credentials never committed; pre-commit guard for credential patterns. |
| SEC-007 | SQL injection prevention via ORM/parameterized queries only; no raw string-built SQL. |
| SEC-008 | Tool allowlists per agent; least-privilege tool permissions enforced by the registry. |
| SEC-009 | Input/output size limits, timeouts, and max graph iterations as denial-of-service controls. |
| SEC-010 | Audit events for: authentication checks, order/account access, tool executions, ticket creation, feedback submission, data deletion. Audit logs SHALL NOT contain secrets or full PII. |
| SEC-011 | Explicit confirmation required before any sensitive action (v1: ticket creation only; refunds/cancellations unsupported). |
| SEC-012 | Rate limiting and request correlation IDs on all chat traffic. |
| SEC-013 | Docker images run as non-root; no secrets baked into images. |

## 6. Integration Requirements

| ID | Requirement |
| --- | --- |
| INT-001 | **LLM providers**: Anthropic Claude (reference), OpenAI, Google Gemini, Ollama, generic OpenAI-compatible — selected via `config/llm.yaml` + env; capability differences documented. |
| INT-002 | **Embeddings**: configurable provider (OpenAI/Anthropic-compatible/Voyage/local via Ollama or sentence-transformers fallback) with dimension validation. |
| INT-003 | **Commerce**: adapter interface (search products, get product, stock, get order, track shipment, return eligibility); mock implementation for v1. |
| INT-004 | **Ticketing**: Jira (REST v3) and ServiceNow (Table/Incident API) adapters behind one interface; configured via `config/app.yaml` + env; mock implementation for tests. |
| INT-005 | **Database**: PostgreSQL 16 + pgvector extension; migrations via Alembic. |
| INT-006 | **Tracing**: optional LangSmith/OTel-compatible export; disabled by default. |
| INT-007 | All integrations SHALL have timeouts, normalized error types, and bounded retries. |

## 7. Data Requirements

| ID | Requirement |
| --- | --- |
| DATA-001 | Tables: users/identity refs, conversations, messages, orders, order_items, products, policy_documents, document_chunks (with embeddings), feedback, support_tickets, tool_executions, audit_events, eval_results. |
| DATA-002 | Primary/foreign keys, unique constraints, indexes (including vector index), timestamps, lifecycle statuses on all core tables. |
| DATA-003 | Async access via SQLAlchemy 2.x; Alembic migrations for every schema change; transactional writes for multi-table operations. |
| DATA-004 | Mock DB orders/products are test fixtures only — production source of truth is the commerce adapter. |
| DATA-005 | Tenant isolation readiness: tenant/store column on conversations, documents, and tickets (single-tenant default). |
| DATA-006 | Document versioning: `policy_documents` track version + content hash; superseded chunks removed or flagged on re-ingest. |

## 8. Acceptance Requirements (global)

A feature is accepted only when:

1. Code and documentation are implemented (no placeholder presented as working).
2. Relevant automated tests pass (`pytest`) — unit, integration, security, e2e as applicable.
3. Error handling and security requirements for the area are addressed and tested.
4. No real credentials are committed; `.env.example` updated if new vars are introduced.
5. Migrations (if schema changed) are created and verified up/down.
6. Acceptance criteria in `TASKS.md` for that task are checked.
7. `TASKS.md` records status, test results, and any limitations.

**Scenario-level acceptance (Phase 10)** — all must pass against mock integrations:

| ID | Scenario |
| --- | --- |
| ACC-001 | Return-policy question → grounded answer with citations. |
| ACC-002 | Order-status question by authenticated customer → authorized order data; by another customer → refused. |
| ACC-003 | Unknown product → no invented product/price/stock; safe abstention or catalog-miss response. |
| ACC-004 | Failed-delivery report → troubleshooting guidance from policies/order data. |
| ACC-005 | Customer reports unresolved issue → bounded retry → ticket created with reference returned. |
| ACC-006 | Ticket creation failure → truthful failure message, escalation preserved, retry available. |
| ACC-007 | Rating + optional comment persisted and retrievable. |
| ACC-008 | Selected LLM provider failure → configured recovery (fallback provider/mock error path) without crashing the API. |
| ACC-009 | Provider switch via config only — no agent/business-logic code changes. |
| ACC-010 | Prompt injection in message and in retrieved document is neutralized and logged. |

## 9. Assumptions

1. Mock commerce data and mock ticketing are sufficient for v1 demonstration and CI.
2. Live LLM calls require operator-supplied API keys in `.env`; tests never need them.
3. Single store (tenant) by default; schema keeps tenant hooks for multi-store later.
4. English-only content in v1.
5. `docker-compose` legacy v1 (1.29.2) or plain `docker run` is available in this environment; compose file targets format compatible with both where possible.
6. `uv` will be installed for dependency management; fallback is `venv + pip` (documented).

## 10. Constraints

1. All work happens inside `ecom-bot/` within the shared parent git repo — never stage sibling projects' files.
2. Local Postgres for `my-exam` occupies port 5433 — this project uses **5434**.
3. No provider, Jira, or ServiceNow credentials present in the environment at time of writing.
4. Framework rule: do not import LangChain/LangGraph into business logic modules unnecessarily.

## 11. Requirement Traceability

Each requirement maps to tasks in `TASKS.md` (Phase ↔ requirement sections):

- Phase 1 → §1, §9, §10 (this document + planning)
- Phase 2 → NFR-001, NFR-006, SEC-006
- Phase 3 → §7 (DATA-*)
- Phase 4 → §5 LLM (FR-015–019 prerequisites), INT-001/002, NFR-007
- Phase 5 → FR-029–037
- Phase 6 → FR-015–028, FR-038–040, SEC-002, SEC-008
- Phase 7 → FR-041–053, FR-046–051
- Phase 8 → FR-001–014, FR-053, NFR-004/005
- Phase 9 → §5 (SEC-*), FR-054–057, NFR-002/003
- Phase 10 → §8 (ACC-*)
