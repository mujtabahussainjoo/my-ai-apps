# AGENTS.md — Project Instructions for All Coding Agents

Portable instructions for any coding agent (Claude Code, OpenCode, Cursor, …) working in
this repository. `CLAUDE.md` adds Claude Code–specific conventions and points here; keep this
file agent-agnostic.

## What this project is

A production-oriented e-commerce AI support chatbot: FastAPI + LangGraph multi-agent
orchestration + RAG (PostgreSQL/pgvector) + provider-independent LLM layer + SSE streaming +
Jira/ServiceNow escalation. Requirements live in `requirement.md`; the task ledger with
statuses and acceptance results is `TASKS.md`; architecture decisions are in `ARCHITECTURE.md`.

## Hard rules (never violate)

1. **One primary task at a time.** Work the task currently marked `IN_PROGRESS` in `TASKS.md`.
   Do not skip ahead. When done: tests green, lint/typecheck green, `TASKS.md` updated with
   status + honest results, then report and continue only if approved or already authorized.
2. **No placeholders presented as working features.** Mock-only integrations must be labeled
   mock-only in code, docs, and `TASKS.md`.
3. **No real credentials.** Secrets come from environment/`.env` only. Commit `.env.example`
   updates, never `.env`. Never log secrets, tokens, payment data, or full PII.
4. **Scope discipline.** Only create/modify files under this project directory. Never stage or
   commit files from sibling directories in the parent git repo.
5. **Security is code, not prompts.** Authorization, ownership checks, validation, and
   idempotency live in application code (`guardrails/`, tools, services) — prompts are not a
   security control.
6. **Business logic stays framework-free.** LangChain/LangGraph imports are allowed only in
   `src/ecommerce_support/llm/`, `agents/`, and `rag/retrieval.py`. Workers/services/tools are
   plain Python so they test without framework runtime.
7. **Verify, never assume.** Run the tests/lint/typecheck you claim to run. If a check cannot
   run (no DB, no creds), record the limitation in `TASKS.md` instead of implying success.
8. **Migrations for every schema change.** Alembic only; verify `upgrade head` and
   `downgrade -1`. No ad-hoc DDL.

## Commands

```bash
make install        # uv sync (venv + lockfile)
make run            # API on :8000
make db-up          # Postgres+pgvector via docker-compose (host port 5434)
make migrate        # alembic upgrade head
make seed           # demo data
make lint           # ruff check
make format         # ruff format
make typecheck      # mypy --strict
make test           # pytest (mocks only; integration tests skip without DB)
make check          # lint + format-check + typecheck + test
```

## Layout conventions

- `src/ecommerce_support/` package, src-layout. Modules mirror `ARCHITECTURE.md` §2
  (api/core/schemas/llm/agents/rag/tools/guardrails/integrations/db/services/workflows).
- Contracts: Pydantic v2 in `schemas/`; DB models in `db/models/`; repositories translate —
  never leak ORM objects into API responses.
- Config: YAML structure in `config/` + env overrides; all loading goes through
  `core/config.py` (validated). No `os.environ` reads elsewhere.
- Tests: `tests/unit`, `tests/integration` (marker `integration`, needs Postgres),
  `tests/security` (marker `security`), `tests/e2e` (marker `e2e`). Tests must pass with zero
  real credentials and zero outbound network.
- Naming: modules `snake_case`, classes `PascalCase`, constants `UPPER_SNAKE`. Type-annotate
  every public function (mypy strict is on).

## Changing LLM providers

Never call a provider SDK from agents/tools. Extend `llm/providers/`, register in
`llm/factory.py`, declare capabilities in `llm/capabilities.py`, select via
`config/llm.yaml` + `LLM_PROVIDER` env. Unsupported capabilities must fail loudly
(`LLMCapabilityError`), not silently degrade.

## Definition of done (per task)

- Code implemented; no TODO-that-lies (real `TODO` comments for known gaps are fine).
- Relevant tests added and passing; `make lint` + `make typecheck` green.
- Errors handled; security requirements for the area addressed.
- Migrations created/verified if schema changed; `.env.example` updated if new vars.
- `TASKS.md` row updated: status, results, limitations.
