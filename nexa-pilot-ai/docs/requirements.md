# Requirements

Derived from `NexaPilot_AI_Workflow.md`. Each requirement lists where it is implemented and
how it is verified. `docs/implementation-status.md` tracks completion honestly.

## Functional

| ID | Requirement | Implementation | Verification |
| --- | --- | --- | --- |
| F1 | Desktop app, not a website-only product; Windows and Ubuntu first | `desktop/` (Tauri 2), `frontend/dist` as the webview bundle | Config + dependency resolution verified; installer build blocked (see status) |
| F2 | Single chat interface with specialized workflows | `frontend/src/pages/ChatPage.tsx`, `agents/supervisor.py` | `test_supervisor.py`, `test_chat_stream.py` |
| F3 | Streaming responses and task-progress events | SSE `/api/chat`, `services/chat_service.py`, event types `routing/token/tool_start/tool_end/...` | `test_chat_stream.py`, `frontend/src/lib/api.test.ts` |
| F4 | Cancellation of an in-flight run | `POST /api/chat/cancel` sets the run's cancel event; `RunCancelledError` stops the graph and marks the run cancelled | `test_chat_stream.py::test_cancel_stops_the_run` |
| F5 | Exactly one active provider, no silent fallback | `provider_config.is_active` unique index, `services/provider_settings.py` | `test_migrations.py`, `test_api.py` |
| F6 | OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible adapters | `providers/` | `test_providers.py` |
| F7 | Connection tests, capability detection, normalized errors | `/api/providers/test`, `ProviderSpec.capabilities`, `core/errors.py` | `test_providers.py`, `test_api.py` |
| F8 | LangGraph agent with typed state, bounded loop, checkpoints | `agents/graph.py`, `agents/llm_loop.py`, `AsyncSqliteSaver` | `test_approval_flow.py`, `test_chat_stream.py` |
| F9 | Research answers with citations and freshness | `tools/web.py`, research prompt, `citations` in state | `test_tools.py`, `test_api.py` |
| F10 | Sandboxed coding: inspect, edit, test, diff | `tools/coding.py` (workspace confinement, command allowlist) | `test_tools.py`, `test_approval_flow.py` (path escape rejected) |
| F11 | Email: multiple accounts, sync, draft, send/forward/delete gated | `integrations/gmail.py`, `imap_mail.py`, `smtp_mail.py`, `services/email_service.py` | Mock-transport tests; live untested |
| F12 | Unified calendar with provenance, time zones, dedupe | `integrations/google_calendar.py`, `services/calendar_service.py`, `integrations/event_extraction.py` | `test_api.py` calendar routes |
| F13 | Travel search/comparison, no fabricated bookings | `integrations/travel.py`, `tools/travel_tools.py` | `test_tools.py` |
| F14 | Finance: timestamped data, portfolio, paper trading, gated live orders | `integrations/market_data.py`, `integrations/broker.py`, `tools/finance_tools.py` | `test_tools.py`, `test_api.py` |
| F15 | Approvals bound to the exact action/arguments, single-use | `services/approvals.py`, `agents/llm_loop.py`, `/api/tools` gate | `test_approval_flow.py`, `test_chat_stream.py` |
| F16 | Audit trail without sensitive content | `services/audit.py`, `audit_log`; approvals + tool executions recorded without arguments | `test_approval_flow.py::test_audit_trail_records_decisions_and_tool_runs` |
| F17 | First-run setup, dependency checks, Ollama guidance | Settings UI integration cards, `/api/health`, `setup_hint` in errors | `test_api.py`, manual smoke test |
| F18 | Upgrade/migration, uninstall and data-retention docs | Alembic `upgrade head` on startup, `docs/installation.md` | `test_migrations.py` |

## Nonfunctional

| ID | Requirement | Implementation |
| --- | --- | --- |
| N1 | Local-first; no telemetry | No analytics; outbound calls only to the configured provider/integrations |
| N2 | Secrets in the OS credential vault, never returned by the API | `core/secrets.py`; keyring probe with explicit degraded fallback |
| N3 | Loopback-only API | `host = 127.0.0.1`, optional bearer-token middleware |
| N4 | Prompt-injection resistance | Email/web/calendar content delimited as untrusted; permissions enforced in code |
| N5 | SSRF protection | `integrations/fetch.py` blocks private/link-local/metadata addresses, re-checks redirects |
| N6 | Bounded resource use | Tool iteration/step caps, timeouts, retries, output truncation |
| N7 | Reproducible builds | `uv.lock`, `frontend/package-lock.json`, `desktop/src-tauri/Cargo.lock` |
| N8 | Cross-platform portability | No OS-specific hard dependency except keyring/libsecret; Tauri targets Windows/Ubuntu |
| N9 | Clear errors | `{code, message, retryable, details, setup_hint}` contract |
| N10 | Accessibility basics | Semantic landmarks, labelled controls, keyboard-usable dialogs |

## Out of scope (documented, not implemented)

- Real payment rails. Travel is search/guidance only; no card data is collected.
- Unattended autonomous purchasing, trading, or email sending.
- macOS installer signing and notarization (architecture is portable; untested).
- Multi-user hosting. The service is a single-user local backend.
