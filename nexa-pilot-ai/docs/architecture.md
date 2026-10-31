# Architecture

## Components

```
┌────────────────────────────── Tauri 2 shell (desktop/) ──────────────────────────────┐
│  Webview: React 19 + TypeScript (frontend/)                                          │
│    hash router -> pages -> hooks (useAgentRun, useToolAction) -> SSE/JSON client      │
│  Rust host: starts/owns the Python backend process, kills it on exit                  │
└───────────────────────────────────────┬──────────────────────────────────────────────┘
                                        │ loopback HTTP + SSE (+ optional bearer token)
┌───────────────────────────────────────▼──────────────────────────────────────────────┐
│ FastAPI app (backend/src/nexapilot)                                                   │
│  api/routes_*      HTTP surface, SSE framing, approval + tool gates                  │
│  services/         chat orchestration, provider settings, approvals, mail/calendar,  │
│                    finance, audit                                                    │
│  agents/           LangGraph state machine, router, bounded tool loop, permissions  │
│  tools/            22 typed tools (web, coding, email, calendar, travel, finance)   │
│  integrations/     provider-agnostic HTTP adapters (search, fetch, market data,      │
│                    travel, Gmail/IMAP/SMTP, Google Calendar, broker, sandbox)        │
│  providers/        OpenAI/Anthropic/Gemini/Ollama/OpenAI-compatible adapters          │
│  core/             settings, paths, logging, errors, secrets, container              │
│  db/               SQLAlchemy models + Alembic migrations (SQLite)                   │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## Data flow: one chat turn

1. `POST /api/chat` validates `ChatRequestSchema`, registers an `asyncio.Event` for
   cancellation in `app.state.active_runs`, and returns a `StreamingResponse`.
2. `ChatService.run_chat` persists the user `Message` and a `TaskRun`, resolves the single
   active provider (raising `ConfigurationError` instead of falling back), and builds a
   `RunContext` (permissions, approval map, cancel event, emitter).
3. `build_graph` executes `classify → agent_<workflow> → finalize`. Classification is
   deterministic keyword scoring (`agents/supervisor.py`); an explicitly requested workflow
   wins. The agent node loads conversation history, filters tools by workflow **and**
   granted permissions, and calls `run_agent_turn`.
4. `run_agent_turn` streams provider events, emits `token`, accumulates tool calls, and
   executes permitted tools with timeouts/retries. Tools needing approval create an
   `ApprovalRequest` bound to `{tool, arguments}` and stop the run with status
   `awaiting_approval`.
5. Events are pushed through an `asyncio.Queue` to the SSE response and mirrored into the
   `TaskRun`/`AuditLog`. `done` carries answer, citations, tool results, provider, and model.
6. On approval, `POST /api/approvals/{id}/decide` updates the record and
   `POST /api/approvals/{id}/resume` replays the exact pending call through the same gate.

## Design decisions

| Decision | Rationale |
| --- | --- |
| `httpx` adapters for every provider/integration | uniform timeouts, streaming, and `MockTransport` tests; no vendor SDK drift or hidden retries |
| Database-enforced single active provider | partial unique index on `provider_config.is_active`; `activate` validates credentials first and never silently falls back |
| Approvals enforced in the tool loop and `/api/tools`, not prompts | prompt wording is not a security boundary; argument-bound, single-use records prevent replay against different targets |
| Deterministic keyword router | reproducible tests and explainable routing; returns confidence/signals instead of a fake probability |
| Workspace-bounded coding tools + command allowlist | prevents traversal/symlink escape and `git push`/force flags; content-changing commands are separate tools |
| LangGraph `AsyncSqliteSaver` checkpointing | approval-blocked or interrupted runs can resume; checkpoints live beside the SQLite DB |
| Settings split: env → `settings.json` overrides | secrets stay in the vault; non-secret preferences are editable from the UI and survive restarts |
| Error contract `{code, message, retryable, details, setup_hint}` | the UI can render a consistent recovery path and the API never leaks provider payloads |
| Keyring probe with explicit file fallback | headless/CI environments still work; Settings reports `degraded` instead of pretending the vault exists |

## Persistence

SQLite (`data_dir()/nexapilot.db`) with Alembic migrations applied on startup. Tables are
singular: `provider_config`, `secret_reference`, `conversation`, `message`, `task_run`,
`approval_request`, `connected_account`, `email_message`, `calendar_event`, `portfolio`,
`position`, `order`, `watchlist_item`, `audit_log`. Checkpoints use
`data_dir()/checkpoints.db`.

## Frontend

Hash-based routing (no server routes), a single `AppProvider` store for settings/notices, and
three streaming hooks. `Markdown` renders a restricted subset itself (no `dangerouslySetInnerHTML`,
only `http(s)` links). Approval cards show action, target, risk, cost, and consequences before
enabling the decision buttons.

## Desktop lifecycle

The Rust host reuses an existing backend on `127.0.0.1:8765`, otherwise launches the bundled
sidecar (`nexapilot-server`), falling back to `uv run nexapilot` in a source checkout. The
child is killed on window exit. The webview only talks to loopback; the CSP allows exactly
that origin.
