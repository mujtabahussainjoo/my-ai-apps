# Testing

## Commands

```bash
# backend
cd backend
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy                    # strict; covers src (see pyproject packages = ["nexapilot"])
uv run pytest                  # 102 tests
uv run pytest tests/security   # approval/secret/path/SSRF regressions
uv run pytest --cov=nexapilot --cov-report=term-missing

# frontend
cd frontend
npm run typecheck
npm test -- --run
npm run build
```

`mypy` is intentionally not run over `tests/` (pytest fixtures and monkeypatching produce
false positives); the application package is fully strict-checked.

## Strategy

| Layer | What is covered |
| --- | --- |
| Unit (`tests/unit`) | provider streaming/tool-call parsing and error normalization, router scoring, tool spec invariants (approval matrix, permission declarations), cancellation |
| Security (`tests/security`) | path traversal and symlink escape, workspace writes, command allowlist/git push rejection, env scrubbing, secret store permissions and keyring fallback, backend description |
| Integration (`tests/integration`) | migrations round trip, provider activation (single active), settings/secrets API, chat SSE with a scripted provider, cancellation, approval creation/decision/resume, `/api/tools` gate, audit trail, workspace 409 hints |
| Frontend (`frontend/src/**/*.test.*`) | SSE frame splitting and malformed frames, typed API error mapping, markdown sanitization |

Everything runs offline. Provider HTTP is exercised through `httpx.MockTransport`; provider
construction during activation uses `FakeProvider`; chat/approval flows use `ScriptedProvider`
so tests are deterministic and free of network flakiness.

## Coverage of acceptance criteria

- Exactly one active provider, switching, deletion: `test_api.py`.
- No silent fallback: `test_chat_without_provider_reports_actionable_error`.
- Streaming, persistence, routing, cancellation: `test_chat_stream.py`.
- Approval isolation/rejection/execution/audit: `test_approval_flow.py`.
- Migrations upgrade→downgrade→upgrade: `test_migrations.py`.
- Path/command/secret protections: `test_security.py`.

## Known gaps in automated coverage

- No live-account tests for Gmail, Google Calendar, Amadeus, or brokers (no credentials).
- No desktop-shell automated test; the Tauri shell is verified by config parsing and
  `cargo generate-lockfile`, not compilation (missing system libraries).
- No load/performance or long-running checkpoint-resume tests beyond the approval resume path.
