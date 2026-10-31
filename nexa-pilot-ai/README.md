# NexaPilot AI

NexaPilot AI is a local-first desktop personal assistant: one chat surface with dedicated
workflows for research, coding, email, calendar, travel, and finance. The desktop shell is
Tauri 2; the agent runtime is Python + FastAPI + LangGraph; the UI is React + TypeScript.

The product is deliberately conservative about side effects. Exactly one model provider is
active at a time, every tool runs with an explicit permission set, and sending email,
deleting data, creating calendar events, booking travel, and placing orders are blocked
behind an approval record bound to the exact arguments the user reviewed.

## Status

Working end to end: provider configuration and switching, streaming chat with cancellation,
deterministic routing, LangGraph tool loop with bounded iterations, approval gating and
resume, the full tool registry, research with citations, sandboxed coding tools, email
(Gmail API + generic IMAP/SMTP), the full Google Calendar v3 resource surface (events, lists,
calendars, ACL, free/busy, settings, watch channels; all writes approval-gated), travel
search, and portfolio/paper-order flows.

Honest gaps, in `docs/implementation-status.md`:

- No live credentials are present in this repository, so cloud provider, Gmail, Amadeus,
  and broker paths are verified with mock transports/scripted providers, not live accounts.
- The Tauri shell compiles and a Ubuntu `.deb` is built (via an extracted WebKitGTK sysroot,
  no root on the build host). Windows/macOS bundles and clean-machine installs are untested;
  see `INSTALL.md` for one-click install/uninstall and `docs/implementation-status.md` for
  remaining packaging gaps.
- Live trading is disabled by default; only paper orders and explicitly enabled, capped
  live orders are supported.

## Layout

```
backend/    FastAPI service, LangGraph agents, tools, integrations, Alembic, tests
frontend/   React 19 + Vite 7 UI, hash routing, SSE client, vitest tests
desktop/    Tauri 2 shell (lifecycle for the Python backend + installers)
install/    one-click install/uninstall scripts (Linux, Windows, macOS)
dist/       built installer (NexaPilot AI_0.1.0_amd64.deb)
docs/       Requirements, architecture, security, integrations, testing, status
```

## Quick start (development)

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+, and (for the
desktop shell) Rust stable plus the Tauri Linux system libraries documented in
`docs/installation.md`.

```bash
# 1. Backend
cd backend
uv sync
uv run nexapilot                 # http://127.0.0.1:8765, OpenAPI at /docs

# 2. UI (second terminal)
cd frontend
npm install
npm run dev                      # http://127.0.0.1:5173, proxies /api to :8765

# 3. Desktop shell (optional, needs Tauri prerequisites)
cd desktop
npm install
npm run dev
```

First run: open **Settings → Model provider**, pick a provider, enter the API key (or point
Ollama at `http://127.0.0.1:11434`), and press **Save & Activate**. The key is written to
the OS credential vault; if no vault is available the backend falls back to a `0600` file
and reports the degraded state in Settings → Runtime and security.

Configuration is environment-driven (`NEXAPILOT_*`, see `.env.example`) with a small set of
UI-editable overrides persisted under the app data directory (`settings.json`).

## Tests

```bash
cd backend  && uv run ruff check src tests && uv run mypy && uv run pytest
cd frontend && npm run typecheck && npm test -- --run && npm run build
```

Current: 102 backend tests and 9 frontend tests pass; ruff and strict mypy are clean on
`backend/src`.

## Security summary

- Backend binds to `127.0.0.1` only; an optional bearer token (`NEXAPILOT_API_TOKEN`) is
  enforced by middleware when set.
- Secrets never travel back over the API; only names, labels, and configured flags.
- SSRF protection on page fetches, workspace confinement for file tools, allowlisted test
  commands, and per-action approval records with an audit log.
- See `docs/security.md` for the threat model and `docs/integrations.md` for scopes.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `no_active_provider` | Activate a provider in Settings; keys and models are validated on save. |
| `secret_store_error` / Settings shows `file (degraded)` | No OS vault in this session (headless/CI). Install a Secret Service provider or accept the `0600` fallback. |
| Chat answers without tools | The workflow's tool permissions are unmet (no account connected, no workspace/search provider configured). |
| `429`/timeouts from a provider | Rate limit or upstream timeout; the error payload is normalized and retryable. |
| Desktop shows "Backend unavailable" | The bundled sidecar may still be starting (the UI retries for ~60s) or it crashed. Check `%APPDATA%\nexapilot\logs\backend.log` (Windows) or `~/.local/share/nexapilot/logs/backend.log`, then press **Retry connection**. |
| Desktop window opens but is blank | Rebuild the bundle after frontend changes; the packaged UI calls `http://127.0.0.1:8765` directly. |

License: proprietary, all rights reserved.
