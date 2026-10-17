# Implementation Plan — E-commerce AI Support Assistant

| Field | Value |
| --- | --- |
| Version | 1.0 |
| Date | 2026-10-16 |
| Status | Approved for planning phase (Phases 2–10 pending review) |

This plan turns the 47 tasks in `TASKS.md` into a concrete execution sequence with quality
gates, verification strategy, and the mock-first rollout of external dependencies.

## 1. Strategy overview

1. **Mock-first**: commerce, ticketing, and LLM providers all ship with mock adapters that are
   exercised by the full test suite. Real providers are added one at a time behind the same
   interfaces and require operator-supplied `.env` keys.
2. **One primary task at a time**: implement → test → lint/typecheck → record in `TASKS.md` →
   next task. No skipping ahead; no placeholder presented as a working feature.
3. **Framework thin, business thick**: LangGraph/LangChain appear only in the orchestration and
   provider layers (`agents/`, `llm/`, `rag/` retrieval glue). Workers call plain Python
   services/tools so business logic stays testable without framework runtime.
4. **Interfaces before integrations**: commerce and ticketing are defined as abstract adapters
   in Phase 3/7 before any provider-specific code.

## 2. Execution sequence and quality gates

| Gate | After tasks | Must pass before continuing |
| --- | --- | --- |
| G1 — Plan | 001–004 | Requirements ↔ architecture consistency review (user sign-off). |
| G2 — Foundation | 005–008 | Service boots via compose; `/health` + `/ready` OK; migration up/down OK; `ruff` + typecheck clean; config validation tested. |
| G3 — Data | 009–011 | Schema validation tests; repository integration tests against Postgres; seed script idempotent. |
| G4 — LLM | 012–015 | Mock provider full-surface tests; factory selection test; retry/timeout/usage tests; no network in CI. |
| G5 — RAG | 016–021 | Ingest → retrieve → cite round-trip on Postgres+pgvector; abstention test; injection-in-doc test; baseline eval numbers recorded. |
| G6 — Agents | 022–028 | Router routes every supported intent; bounded-iteration test; ownership/security tests on all tools; resolution retry bounded. |
| G7 — Escalation | 029–034 | Mock ticket success + failure + duplicate-submission tests; idempotency verified; truthful failure path. |
| G8 — API | 035–038 | e2e chat over SSE with mock provider; persistence after tool failure; auth/rate-limit/security tests. |
| G9 — Production readiness | 039–044 | Full suite green on mocks; lint/type/security gates; clean-start deployment verified. |
| G10 — Delivery | 045–047 | ACC-001–010 recorded; provider-switch verified; delivery report published. |

## 3. Per-phase execution notes

### Phase 2 — Foundation (TASK-005–008)
- Install `uv` (fallback: `venv` + `pip`); pin every dependency in `pyproject.toml`; commit lockfile.
- Baseline pins (verify compatibility at install time): `fastapi`, `uvicorn[standard]`,
  `pydantic>=2.9,<3`, `sqlalchemy[asyncio]>=2.0.30`, `alembic`, `asyncpg`/`psycopg[binary]`,
  `pgvector`, `httpx`, `langgraph`, `langchain-core`, `langchain-anthropic/openai/google`,
  `pyyaml`, `python-dotenv`, `structlog`, `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`,
  `mypy`, `aiosqlite` (tests), `fakeredis`/`slowapi` (rate limit).
- Config precedence: defaults → `config/*.yaml` → environment variables → `.env` (never committed).
- DB: compose service `ecom-bot-pg` (pgvector/pg16) on host port **5434**; container name
  distinct from `myexam-pg` (port 5433 — do not touch).

### Phase 3 — Data (TASK-009–011)
- Schemas (`schemas/`) are the API/agent contracts; DB models (`db/models/`) are persistence;
  repositories translate. No leakage of ORM objects into API responses.
- Seed data: ≥12 products across 4 categories, ≥5 orders in varied states across ≥3 customers,
  ≥2 policy documents; deterministic IDs for tests.

### Phase 4 — LLM (TASK-012–015)
- Interface (`llm/base.py`): `complete`, `stream`, `structured`, `with_tools` — all async,
  returning normalized `LLMResult`/`LLMChunk`/usage objects.
- Capability matrix per provider (`llm/capabilities.py`); requesting an unsupported feature
  raises `LLMCapabilityError` at startup/call time — never silent degradation.
- Retry policy: max 3 attempts, exp backoff with jitter, retry only on transient classes
  (timeout, 429, 5xx); never retry on auth/validation errors.

### Phase 5 — RAG (TASK-016–021)
- Defaults (rationale in `docs/rag-pipeline.md`): chunk size 1000 chars, overlap 150,
  top-k 5, threshold cosine distance ≤ 0.35 (configurable), optional cross-encoder rerank off by default.
- Embedding dimension validated at startup and on provider switch; mismatch fails fast.
- Citations carry `{document_id, version, chunk_id, section_title, score}`.

### Phase 6 — Agents (TASK-022–028)
- LangGraph `StateGraph` with typed `AgentState`; nodes: `route → worker → resolve → end`.
- Every tool call flows through the registry (validation + permission + audit + idempotency).
- Router: deterministic fast-path (patterns for order/tracking/return/product/account/ticket)
  → LLM classifier fallback → `general`/`clarify` safety net. Max 3 routing hops per request.

### Phase 7 — Escalation (TASK-029–034)
- State machine (`workflows/resolution.py` + `workflows/ticket_lifecycle.py`) is the single
  source of truth for transitions; agents request transitions, the workflow validates them.
- Idempotency: deterministic key = `conversation_id + issue_fingerprint`; persisted in
  `support_tickets`; duplicate create returns existing ticket.

### Phase 8 — API (TASK-035–038)
- SSE over `StreamingResponse` with `text/event-stream`; event payload envelope
  `{event, request_id, conversation_id, data}` documented in `docs/api-reference.md`.
- JWT auth via `python-jose`/`pyjwt` with HS256 dev secret from env; `admin` scope protects
  document ingest and eval endpoints.

### Phase 9 — Production readiness (TASK-039–044)
- Guardrails layered: API middleware → graph entry → tool/service → output validator.
- Full suite must run with **zero** real credentials and **zero** outbound network.
- Deployment verified from a clean checkout: `docker compose up` → seed → ingest → chat.

### Phase 10 — Delivery (TASK-045–047)
- Scenario runner (`tests/e2e/test_scenarios.py`) executes ACC-001–010 against mocks and
  writes a machine-readable result set referenced by the delivery report.

## 4. Verification strategy

| Layer | Tooling | Notes |
| --- | --- | --- |
| Unit | `pytest tests/unit` | Pure logic; mock providers/adapters. |
| Integration | `pytest tests/integration` | Real Postgres+pgvector via compose; mock LLM/ticketing. |
| Security | `pytest tests/security` | Cross-tenant access, injection, leakage, forged IDs, duplicates. |
| E2E | `pytest tests/e2e` | Full FastAPI app (httpx ASGI) + graph + DB + mocks. |
| Quality | `ruff check`, `ruff format --check`, `mypy` | Run via `make lint` / `make typecheck`. |
| Migration | `alembic upgrade head` + `downgrade -1` round-trip in CI script. |
| Eval | `scripts/evaluate_rag.py` | Baseline recorded in `docs/rag-pipeline.md`. |

## 5. Risk register

| Risk | Mitigation |
| --- | --- |
| No compose v2 in environment | Makefile prefers `docker compose` v2 (installed to `~/.docker/cli-plugins`) and falls back to legacy `docker-compose`; compose file validated with `docker compose config`. |
| No LLM credentials | Mock provider is the CI default; live adapters gated by env presence. |
| LangChain/LangGraph churn | Pin exact versions in lockfile; confine framework imports to `llm/`, `agents/`, `rag/retrieval.py`. |
| pgvector dimension mismatch | Startup + ingestion dimension check; fail fast with clear error. |
| Duplicate tickets on retry | Idempotency keys + persistence + security test ACC/SEC cases. |
| Prompt injection via docs | Document sanitation + untrusted-content delimiters + output guardrails + tests. |
| Sibling git changes | Only `ecom-bot/**` ever staged; commit messages scoped accordingly. |

## 6. Definition of done (task-level)

See `requirement.md` §8. Globally: every task ends with a recorded status, test results, and
any limitations in `TASKS.md`; features that are mock-only are labeled mock-only everywhere
they appear.
