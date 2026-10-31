# AGENTS.md

Instructions for coding agents working in this repository.

## Layout and commands

- `backend/` — Python 3.12, uv, FastAPI, LangGraph, SQLAlchemy/Alembic, pytest.
  - `uv sync`, `uv run nexapilot`, `uv run pytest`
  - `uv run ruff check src tests && uv run ruff format src tests`
  - `uv run mypy` (strict; configured for `src` only — do **not** add `tests` to mypy)
- `frontend/` — React 19 + Vite 7 + TypeScript (strict).
  - `npm run dev`, `npm run typecheck`, `npm test -- --run`, `npm run build`
- `desktop/` — Tauri 2 shell. `npm run dev` / `npm run build` require Rust and the Linux
  webkit2gtk/rsvg development packages.
- Root `Makefile` wraps the common flows (`make verify`).

## Invariants — do not break these

1. **One active provider.** `provider_config.is_active` is protected by a partial unique
   index. Never add fallback logic that silently calls another provider.
2. **Approvals are enforced in code.** Any new tool with external side effects must set
   `requires_approval=True` and an `approval_action`, and must be exercised through the same
   gate in `agents/llm_loop.py` and `api/routes_tools.py`. Validate arguments *before*
   creating an approval.
3. **Permissions come from configuration, not the model.** New tools declare
   `ToolSpec.permissions`; they are filtered by `agents/permissions.py` and checked by
   `ToolContext.require_permissions`.
4. **Secrets never leave the vault.** Use `core/secrets.py`; never return secret values from
   an API or log them. New secret names must be added to `KNOWN_SECRETS` in
   `api/routes_settings.py`.
5. **Loopback only.** Keep the backend bound to `127.0.0.1`; do not add permissive CORS or
   disable the API-token middleware.
6. **Normalized errors.** Raise `NexaPilotError` subclasses (never `HTTPException` with a
   dict `detail`) so the UI receives `{code, message, retryable, details, setup_hint}`.
7. **Bounded work.** Every new loop/command/HTTP call needs a timeout; keep tool iterations
   and output sizes capped.
8. **Filesystem and command safety.** Coding tools resolve paths inside the workspace and
   reject escapes; commands run without a shell against the allowlist in
   `integrations/sandbox.py`.
9. **DB schema changes require a migration.** Alembic revisions live in
   `backend/alembic/versions`; table names are singular (e.g. `provider_config`).
10. **Tests stay offline and deterministic.** Use `httpx.MockTransport`, `FakeProvider`, or a
    scripted provider; never call real APIs in tests.

## Conventions

- Backend: type hints everywhere, `from __future__ import annotations`, structlog for logs,
  Pydantic v2 models at boundaries, no comments unless they explain a non-obvious *why*.
- Frontend: no additional runtime dependencies without a strong reason; keep the SSE client
  in `src/lib/api.ts`, hooks for stateful streaming, presentational pages thin.
- Docs: keep `docs/implementation-status.md` and `docs/audit-checklist.md` honest. Do not
  claim live/verified behavior for untested integrations.

## Before finishing a change

Run `make verify` (or at minimum ruff, ruff format --check, mypy, pytest, `npm run typecheck`,
`npm test -- --run`, `npm run build`). Update docs/status when behavior or limitations change.
