# Task Plan — E-commerce AI Support Assistant

Statuses: `TODO` · `IN_PROGRESS` · `BLOCKED` · `DONE`
Rules: one primary task at a time; a task is `DONE` only when acceptance criteria pass and
results are recorded below. Limitations must be recorded honestly.

---

## Phase 1 — Requirements and planning

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-001 | Inspect repository and record environment | — | Repo inspected; structure, tooling, constraints reported | **DONE** | 2026-10-16: `ecom-bot/` empty (greenfield). Parent git repo `/var/www/html/my-ai-apps` with uncommitted sibling changes — never stage outside `ecom-bot/`. Python 3.12.3 ✓, pip ✓, uv ✗ (install planned), Docker daemon up, compose v2 ✗ / legacy `docker-compose` 1.29.2 ✓, `myexam-pg` pgvector container on port 5433 → use 5434. No provider/Jira/ServiceNow/DB creds in env. PyPI reachable. No blocking decisions. |
| TASK-002 | Create `requirement.md` | 001 | Functional, non-functional, security, integration, data, and acceptance requirements documented | **DONE** | 2026-10-16: `requirement.md` v1.0 created — FR-001–057, NFR-001–013, SEC-001–013, INT-001–007, DATA-001–006, ACC-001–010, assumptions/constraints. |
| TASK-003 | Create `TASKS.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md` | 002 | Task plan with deps/acceptance/statuses, execution sequence, and architecture docs exist and are consistent with requirements | **DONE** | 2026-10-16: All three documents created; 47 tasks with dependencies and acceptance criteria; architecture mermaid diagrams + ADR table. |
| TASK-004 | Document components, workflows, decisions, dependencies | 003 | Requirements + architecture reviewed for consistency before implementation begins | **DONE** | 2026-10-16: Deliverables in `ARCHITECTURE.md`; self-review consistency check passed; user approved review gate ("continue") → Phase 2 authorized. |

## Phase 2 — Project foundation

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-005 | Initialize packaging, deps, env config, code-quality tools | 004 | `pyproject.toml` + lockfile, pinned deps, ruff + type-checker configured, `.env.example` + `.gitignore`, venv functional | **DONE** | 2026-10-16: `uv 0.13.1` installed (official installer; system pip is PEP-668 locked). Created `pyproject.toml` (pinned ranges + dev group), `uv.lock`, `.python-version` (3.12), `.gitignore`, `.env.example` (~45 documented vars), `Makefile`, `README.md`, `src/ecommerce_support/__init__.py`. Verified: `uv sync` OK (fastapi 0.143.3, langgraph 0.6.11, langchain-core 0.3.86, sqlalchemy 2.0.54, alembic 1.20.0, pydantic 2.14.1, asyncpg 0.32.0, pgvector 0.5.1); `ruff check` ✓; `ruff format --check` ✓; `mypy src` ✓. |
| TASK-006 | Create `AGENTS.md`, `CLAUDE.md`, rules, skills, agent settings | 005 | Agent instruction files + modular rules + ≥3 skills created; no secrets | **DONE** | 2026-10-16: Created `AGENTS.md` (portable hard rules), `CLAUDE.md`, `.claude/settings.json` (permissions allow/deny + precheck hook; JSON validated), `.claude/rules/{python,security,testing,architecture}.md`, `.claude/skills/{ecommerce-support,rag-development,agent-development}/SKILL.md` (valid frontmatter), `scripts/hooks/precheck.sh`. Verified hook: exit 0 on clean file, exit 2 with ruff report on unfixable violation; found+fixed a bug (hook cd'd to parent git toplevel → now uses script-relative project root). No secrets; deny rules block `.env`/git commit. |
| TASK-007 | Config loading, structured logging, errors, health endpoints | 005 | YAML+env config with Pydantic validation; JSON logs with trace IDs; `/health` + `/ready` respond; unit tests pass | **DONE** | 2026-10-16: Created `config/{app,llm,agents,rag,guardrails}.yaml`; `core/{config,logging,exceptions,observability}.py`; `api/{middleware,dependencies,routes/health}.py`; `main.py` (app factory + exception handlers); `tests/{conftest.py,unit/test_{config,exceptions,logging,health}.py}`; updated `.env.example` to `SECTION__FIELD` interface. Config = YAML defaults < env/.env overrides (nested `__` delimiter), validated (prod rejects default JWT secret/mock provider); redacted `security_summary()`. Logging = structlog JSON with auto request/conversation ids + secret redaction. Pure-ASGI middleware sets `X-Request-ID`/`X-Process-Time` so contextvars reach endpoints. Verified: `make check` green (23 tests, ruff, format, mypy strict on 12 files); live uvicorn smoke test → `/health` 200 + `/ready` 200 with headers. Bug fixed: instance `retryable` shadowed class default in `AppError`. |
| TASK-008 | Docker Compose, PostgreSQL+pgvector, SQLAlchemy, Alembic | 007 | Service starts via compose (port 5434), DB connects, initial migration runs up/down, README commands verified | **DONE** | 2026-10-17: Docker Compose v2 (v5.6.0) CLI plugin installed to `~/.docker/cli-plugins` — legacy `docker-compose` 1.29.2 is broken by urllib3 v2 (`http+docker` scheme), so ADR D-014 updated; Makefile `COMPOSE` auto-detects v2 else falls back to v1. `docker-compose.yml` (db `ecom-bot-pg` pgvector/pg16 → host 5434, api → 8010, healthchecks, named volume), multi-stage `Dockerfile` (uv, non-root uid 10001, healthcheck), `.dockerignore`. `db/base.py` (DeclarativeBase), `db/session.py` (async engine/session, `session_scope`, `close_engine`, `check_database` readiness); `main.py` disposes engine on shutdown; Alembic async `env.py` reads `DATABASE__URL` from validated config; initial migration `50f0c29c7ff2` enables the `vector` extension (TASK-010 adds tables, TASK-018 the embedding column/index). `tests/integration/test_database.py` (marker `integration`, auto-skip when DB unreachable). Verified: `docker compose config` valid; `make db-up` → healthy on 5434; `make migrate` enables `vector`; `make migrate-down` drops it + clears `alembic_version`; re-`make migrate` re-enables (round-trip OK); `docker compose build api` OK; `docker compose up -d` → both containers healthy; `curl :8010/health`+`/ready` 200 (database connected); local `make run` → `/ready` database connected. `make check` green (26 tests: 23 unit + 3 integration, run against live DB; 3 skipped with DB down). Bug fixed: `alembic/env.py` import order (ruff); Dockerfile missing `README.md` broke hatchling build. |

## Phase 3 — Database and contracts

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-009 | Define Pydantic schemas and shared domain models | 007 | Schemas for chat, agents, orders, products, feedback, tickets with validators; unit tests pass | **DONE** | 2026-10-17: New `schemas/` package (Pydantic v2, framework-free). Modules: `enums.py` (MessageRole, ConversationStatus with FR-047 lifecycle values, Intent, AgentName, OrderStatus, StockStatus, TicketProvider/Status, Priority, DocumentStatus, ToolCallStatus), `common.py` (`Schema` with `extra="forbid"` + whitespace strip, `ORMReadableSchema` with `from_attributes`, `ErrorDetail`/`ErrorResponse` mirroring the API error envelope, `PageParams`, generic `Page[T]`), `chat.py` (ChatRequest with blank/length validators, Message, Conversation, ConversationSummary, ChatResponse), `agents.py` (RoutingDecision, AgentState graph state, ToolCallRequest, ToolExecution, SourceCitation, AgentResponse), `orders.py` (Address, OrderItem, Order, OrderSummary, Shipment/Event, ReturnEligibility), `products.py` (Product, ProductSummary, ProductSearchQuery with price-range validator, StockInfo), `accounts.py` (UserProfile with normalized email pattern, AccountSummary — no secrets), `feedback.py` (FeedbackRequest rating 1–5, comment trim-to-None; Feedback), `tickets.py` (TicketRequest with redaction boundary, Ticket, TicketStatusResponse), `documents.py` (PolicyDocument, DocumentChunk, RetrievalQuery/Hit/Result with abstention). Exact-currency/money validators (Decimal, non-negative, 2 dp), enum bounds, and extra-field rejection covered. Verified: `make check` green — 63 tests (37 new in `tests/unit/test_schemas.py`), ruff + format + mypy strict clean. Note: added `accounts.py` and `documents.py` beyond the six named areas for FR-023/FR-029–034 completeness. |
| TASK-010 | Database models, repositories, initial migrations | 008, 009 | All DATA-001 tables modeled; Alembic migration; repository tests against Postgres pass | **DONE** | 2026-10-17: All 13 DATA-001 tables modeled in `db/models/` (users, conversations, messages, products, orders, order_items, policy_documents, document_chunks, feedback, support_tickets, tool_executions, audit_events, eval_results) with `CreatedAt`/`Timestamp` mixins, non-native `VARCHAR(32)` enum columns + named `CHECK` constraints (`enum_column_type`, `create_constraint=True`), deterministic naming convention in `db/base.py`, app-generated `String(64)` ids (`core/ids.new_id`). DATA-005 tenant column on conversations/documents/tickets; DATA-006 version + content hash + unique `(tenant_id, source, version)`; `document_chunks.embedding vector(1536)` with HNSW `vector_cosine_ops` index (FR-031). Migration `dec95a6bfcee` (revises `50f0c29c7ff2`) autogenerated + reviewed (fixed pgvector `Vector` import); `upgrade head`/`downgrade -1`/re-`upgrade` round-trip verified; autogenerate re-run reports **no drift**. Repositories in `db/repositories/` (user, conversation, product, order, document, feedback, ticket, audit, tool_execution, eval_result) translate ORM→Pydantic schemas, never return ORM objects, never commit, and use explicit `selectinload` (fixed 4 `MissingGreenlet` async lazy-load bugs in conversation/order). Tests: `tests/integration/test_repositories.py` (13 tests, transaction-rollback per test) + shared `tests/integration/conftest.py`; added `schemas/audit.py` + `schemas/eval.py`; enabled mypy SQLAlchemy plugin. `make check` green — 76 passed (ruff + format + mypy strict on 54 files). Docs: `docs/database-schema.md` (referenced by ARCHITECTURE §9). Limitation: verified against the compose DB reachable at `DATABASE__URL` (localhost:5434); environment has overlapping Docker networks, so `docker exec ecom-bot-pg psql` may not reflect that same server. |
| TASK-011 | Mock commerce data + seed script | 010 | `scripts/seed_demo_data.py` loads products/orders/users deterministically; idempotent; test verifies | **DONE** | 2026-10-17: `scripts/seed_demo_data.py` seeds deterministic, fixed-ID fixtures — 2 users, 8 products (varied categories/stock statuses incl. out-of-stock/backorder), 3 orders (5 line items) with addresses/shipments/events. `seed_demo_data(session)` writes only via repository `upsert`/`upsert_many` (caller owns transaction); CLI `main()` wraps `session_scope` + `close_engine`; `make seed` wired. Added `scripts/__init__.py`; pyproject `pytest pythonpath=["."]`, ruff `known-first-party=[ecommerce_support, scripts]`, and a documented filter for a known asyncpg teardown `RuntimeWarning`. Tests: `tests/integration/test_seed_data.py` (3 tests — expected rows, idempotency, updates). Verified: `make seed` run twice → identical counts; DB shows users=2/products=8/orders=3/order_items=5 (no duplicates). Also hardened `tests/integration/test_repositories.py` against committed seed data (unique categories/tenants/datasets; `begin_nested` savepoints for the two CHECK-constraint tests). `make check` green — 79 passed, ruff + format + mypy strict clean. Limitation: seeding commits demo fixtures to the DB by design (test-only source per DATA-004); it does not seed policy documents (covered by TASK-017/018 ingestion). |

## Phase 4 — LLM foundation

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-012 | Provider-independent LLM interface | 009 | `llm/base.py` ABC with complete/astream/structured/tool-call contracts; mock implements all; tests pass | **DONE** | 2026-10-17: New `llm/` package (framework-firewall respected). `llm/types.py` provider-neutral contracts (`Role`, `ChatMessage`, `ToolCall`, `ToolDefinition`, `ToolCallResult`, `Usage`, `CompletionRequest`, `CompletionResponse`, `StreamChunk`) — no provider SDK types leak. `llm/capabilities.py` (`LLMCapability` StrEnum: complete/stream/structured/tool_calling/vision; `ensure_capability` raising `LLMCapabilityError` loudly). `llm/base.py` `LLMClient` ABC: `model_name`, `complete`, `astream` (async iterator of `StreamChunk`), `structured[T: BaseModel]`, `tool_call`, plus `supports`/`require`/`aclose`. `llm/providers/mock.py` `MockLLMClient` implements **all four** contracts deterministically (echo fallback + scriptable queues for completions/structured/tool-calls; optional injected model name/chunk size; records requests for assertions). Tests: `tests/unit/test_llm.py` (21 tests — abstractness, capability declaration + `LLMCapabilityError`, complete echo/scripted/model-override, astream reassembly+termination+iterator, structured model/dict/unscripted/mismatch, tool-call scripted/empty, aclose, bad chunk size). `make check` green — 100 passed (+21), ruff + format + mypy strict on 60 files. Note: factory (`llm/factory.py`) and real adapters are TASK-013 scope. |
| TASK-013 | First provider adapter (Anthropic) + mock adapter | 012 | Anthropic adapter behind interface; mock adapter for tests; factory selects via config; tests pass without network | **DONE** | 2026-10-17: `llm/providers/anthropic.py` `AnthropicLLMClient` implements all four contracts over the Messages API — request mapping (system extraction, user/assistant/tool turns, tool_use blocks, stop/temperature/max_tokens/model), response mapping (text + tool_use blocks → `CompletionResponse` + `Usage`), streaming via `messages.stream` with a terminal `done` chunk, `structured` via a forced `emit_structured_output` tool validated against the Pydantic schema, and `tool_call` with tool/tool_choice mapping. SDK errors normalized to `LLMAuthError`/`LLMRateLimitError`/`LLMTimeoutError`/`LLMError`; SDK-internal retries disabled (`max_retries=0`) so our layer owns retry policy (TASK-015). Injectable client (type-cast) enables offline tests with real anthropic response types. `llm/factory.py` `create_llm_client(config, role="generation"|"router")` selects mock/anthropic via config only (router provider/model honored; missing key or unimplemented provider raises `ConfigurationError`); `get_llm_client()` wrapper over settings. Mock adapter reused unchanged. Tests: `tests/unit/test_llm_factory.py` (7) + `tests/unit/test_llm_anthropic.py` (13) run fully offline (fake transport, no creds/network). `make check` green — 120 passed (+20), ruff + format + mypy strict on 62 files. Note: OpenAI/Gemini/Ollama/compatible adapters and the documented capability matrix are TASK-014; retries/backoff/timeout normalization are TASK-015. |
| TASK-014 | Additional providers + capability checks | 013 | OpenAI, Gemini, Ollama, OpenAI-compatible adapters; capability matrix documented; feature gaps fail loudly | TODO | |
| TASK-015 | Streaming, error normalization, retries, timeouts, usage tracking | 013 | Typed errors; bounded retry/backoff; per-call timeouts; token/cost tracking; failure injection tests pass | TODO | |

## Phase 5 — RAG

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-016 | Document loading and text normalization | 007 | Loaders for md/txt/pdf/html with type/size validation + normalization; unit tests | TODO | |
| TASK-017 | Chunking, versioning, ingestion tracking | 016 | Configurable chunker; document versions + content-hash dedupe; ingestion status/errors persisted | TODO | |
| TASK-018 | Embeddings + pgvector persistence | 017, 010 | Configurable embedding provider (mock for tests); chunks+embeddings stored in pgvector; dimension validation; migration for vector extension | TODO | |
| TASK-019 | Retrieval, metadata filtering, optional reranking | 018 | Semantic search with top-k/threshold/metadata filters; reranker optional/configurable; unit+integration tests | TODO | |
| TASK-020 | Grounded generation, citations, abstention | 019, 013 | Answers cite document+chunk; abstain path tested; injection-in-document test passes | TODO | |
| TASK-021 | RAG eval dataset + baseline metrics | 020 | Versioned eval set + `evaluate_rag.py` baseline recall/groundedness reported | TODO | |

## Phase 6 — Tools and agents

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-022 | Typed tool registry + permission checks | 009 | Registry with Pydantic validation, per-agent allowlists, audit hooks; security tests | TODO | |
| TASK-023 | Order worker + commerce adapter | 022, 011 | Order tools via adapter; ownership checks; unit tests incl. cross-customer denial | TODO | |
| TASK-024 | Product worker + catalog adapter | 022, 011 | Search/details/stock tools; never invents data; tests | TODO | |
| TASK-025 | Policy RAG worker | 022, 020 | Worker calls retrieval + grounded generation with citations; abstention; tests | TODO | |
| TASK-026 | Account worker + authorization | 022 | Authorized account Q&A; strict ownership; no secret exposure; security tests | TODO | |
| TASK-027 | SuperAgent/Router + LangGraph state | 013, 023–026 | Graph routes all supported intents; bounded iterations; fallback path; router unit tests | TODO | |
| TASK-028 | Resolution Agent + bounded retry flow | 027 | Resolution check, bounded alternative retry, escalation trigger; state-transition tests | TODO | |

## Phase 7 — Feedback and escalation

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-029 | Customer resolution-confirmation flow | 028 | Ask-resolved interaction in chat; transitions per state machine; tests | TODO | |
| TASK-030 | Feedback persistence + reporting endpoints | 029, 010 | Rating/comment stored w/ conversation+outcome; `POST /api/v1/feedback`; tests | TODO | |
| TASK-031 | Ticketing provider interface + mock integration | 022 | Adapter interface (create/get status); mock confirmed-success + failure modes; tests | TODO | |
| TASK-032 | Jira integration | 031 | Jira REST adapter, config-driven, redacted payload builder; tests with mocked HTTP | TODO | |
| TASK-033 | ServiceNow integration | 031 | ServiceNow incident adapter; config-driven; mocked HTTP tests | TODO | |
| TASK-034 | Ticket lifecycle, idempotency, retry safety, failure handling | 031–033, 028 | Idempotency keys; `TICKET_CREATION_FAILED` path truthful; duplicate-prevention tests; ACC-005/006 pass | TODO | |

## Phase 8 — API and streaming

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-035 | Versioned FastAPI endpoints | 027–034 | chat/conversations/feedback/tickets/documents/health per spec; OpenAPI; validation tests | TODO | |
| TASK-036 | SSE chat streaming + documented event schemas | 035, 015 | All lifecycle events per FR-010; docs + example client; disconnect handling; mock-provider tests | TODO | |
| TASK-037 | Conversation history + message persistence | 035, 010 | History endpoints; persistence incl. after tool failures; pagination; tests | TODO | |
| TASK-038 | Auth, rate limiting, request validation, API errors | 035 | JWT auth; ownership enforced; rate limits; safe error responses; security tests | TODO | |

## Phase 9 — Security, quality, deployment

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-039 | Complete guardrail layer + tests | 022–038 | Input/output validation, prompt-injection, PII, authorization policies; SEC-* tests pass | TODO | |
| TASK-040 | Unit, integration, security, e2e test suites | all | Full suite green with mocks only; no credentials required; coverage of FR-critical paths | TODO | |
| TASK-041 | Evaluation, tracing, metrics, operational logs | 041 deps | Trace IDs end-to-end; metrics (FR-055) recorded; eval script integrated; no sensitive logging | TODO | |
| TASK-042 | Docker deployment + environment docs | 008, 035 | Dockerfile, compose, `.env.example`, deployment doc verified from clean start | TODO | |
| TASK-043 | Full test/lint/type/migration/security check run | 039–042 | All gates pass or failures documented with cause + remediation | TODO | |
| TASK-044 | README, API docs, troubleshooting, runbooks | 043 | Complete docs; setup from scratch verified; known limitations listed | TODO | |

## Phase 10 — Final verification

| ID | Title | Deps | Acceptance criteria | Status | Results / notes |
| --- | --- | --- | --- | --- | --- |
| TASK-045 | Run all customer support scenarios vs mocks | 044 | ACC-001–008 executed and recorded | TODO | |
| TASK-046 | Verify provider switching, RAG grounding, authz, feedback, escalation | 045 | ACC-009/010 + spot checks recorded | TODO | |
| TASK-047 | Final delivery report | 046 | Implemented features, test results, config requirements, limitations, next steps | TODO | |

---

## Execution log (append per task)

- 2026-10-16 — TASK-001 DONE (inspection report delivered in session; results in table above).
- 2026-10-16 — TASK-002 DONE (`requirement.md`).
- 2026-10-16 — TASK-003 DONE (`TASKS.md`, `IMPLEMENTATION_PLAN.md`, `ARCHITECTURE.md`).
- 2026-10-16 — TASK-004 DONE (consistency review passed; user approved Phase 2).
- 2026-10-16 — TASK-005 DONE (packaging/deps/tooling; `uv` installed).
- 2026-10-16 — TASK-006 DONE (agent instructions, rules, skills, settings hook).
- 2026-10-16 — TASK-007 DONE (config, logging, errors, health endpoints).
- 2026-10-17 — TASK-008 DONE (compose v2 + Postgres/pgvector, async SQLAlchemy, Alembic baseline migration up/down; see table).
- 2026-10-17 — TASK-009 DONE (`schemas/` Pydantic v2 contracts + 37 unit tests; see table).
- 2026-10-17 — TASK-010 DONE (13 ORM models + repositories + migration `dec95a6bfcee` up/down, no drift; `docs/database-schema.md`; 76 tests green; see table).
- 2026-10-17 — TASK-011 DONE (deterministic idempotent seed script + 3 integration tests; 79 tests green; see table).
- 2026-10-17 — TASK-012 DONE (provider-independent `LLMClient` ABC + capabilities + deterministic mock provider; 100 tests green; see table).
- 2026-10-17 — TASK-013 DONE (Anthropic adapter + config-only factory; offline tests with fake transport; 120 tests green; see table).
