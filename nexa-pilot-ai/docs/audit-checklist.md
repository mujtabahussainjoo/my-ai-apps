# Universal architecture audit checklist

The workflow document refers to a “separate universal architecture audit checklist”, but no
such file existed in this repository or its parent at implementation time. This document is
the checklist that was authored and applied instead. It is deliberately generic and each
item records the outcome for NexaPilot.

Legend: **Pass** / **Pass with gap** / **Gap** / **N/A**.

| # | Check | Outcome | Evidence |
| --- | --- | --- | --- |
| A1 | Clear product boundary and non-goals | Pass | `README.md`, `docs/requirements.md` (out of scope) |
| A2 | Explicit component boundaries | Pass | `docs/architecture.md` diagram; `api/services/agents/tools/integrations/providers/core/db` |
| A3 | Single source of configuration with validation | Pass | `core/config.py` (pydantic-settings), `core/settings_store.py` allowlist |
| A4 | Secrets out of source and out of the database | Pass | `core/secrets.py`; `test_api.py::test_api_key_is_stored_in_secret_store_not_database` |
| A5 | Secrets never returned by read APIs | Pass | `/api/settings/secrets` returns names/flags only |
| A6 | Credential-store failure is explicit, not silent | Pass | keyring probe + `degraded` reporting; `test_keyring_falls_back_to_file_when_no_vault` |
| A7 | Local-only network surface | Pass | host `127.0.0.1`, optional bearer token middleware, CORS allowlist, CSP |
| A8 | Normalized error contract | Pass | `core/errors.py`, `test_api.py` error assertions |
| A9 | Actionable remediation in errors | Pass | `setup_hint` in every error payload and UI callouts |
| A10 | Authorization enforced in code, not prompts | Pass | permission sets + approval gate; `test_approval_flow.py` |
| A11 | Approval bound to exact action/target/args | Pass | approval payload match in `llm_loop` and `/api/tools` |
| A12 | Approval is single-use and not replayable for other targets | Pass | status transition + argument equality; tests for rejection/scope |
| A13 | Audit trail without sensitive payloads | Pass with gap | tool + approval audit; activation not audited (documented) |
| A14 | Input validation at every boundary | Pass | Pydantic request models, tool arg schemas, provider event validation |
| A15 | Output treated as untrusted | Pass | markdown renderer escapes HTML, only `http(s)` links |
| A16 | SSRF protection with redirect re-validation | Pass | `integrations/fetch.py`, security tests |
| A17 | Filesystem confinement incl. symlinks | Pass | `tools/coding.py`, traversal/symlink tests |
| A18 | Command execution without a shell, allowlisted | Pass | `integrations/sandbox.py`, security tests (`git push`, `-exec`, env scrub) |
| A19 | Bounded loops, timeouts, retries, output caps | Pass | `max_tool_iterations`, provider/tool timeouts, `max_output_bytes` |
| A20 | Cancellation propagates to provider and tools | Pass | `RunCancelledError`, `/api/chat/cancel`, `test_cancel_stops_the_run` |
| A21 | Durable state with migrations | Pass | Alembic initial revision, upgrade/downgrade test |
| A22 | Restart/resume story for interrupted work | Pass with gap | checkpoint saver + approval resume; no test for process restart mid-stream |
| A23 | Single active provider, no silent fallback | Pass | partial unique index + activation validation + tests |
| A24 | Provider capability reporting is honest | Pass | capability flags per spec surfaced in Settings |
| A25 | Reproducible dependencies | Pass | `uv.lock`, `frontend/package-lock.json`, `Cargo.lock` |
| A26 | Tests are deterministic and offline | Pass | mock transports/scripted providers throughout |
| A27 | Frontend type safety and tests | Pass | strict TS, vitest for SSE/markdown |
| A28 | Accessibility basics | Pass with gap | labels/landmarks/keyboard focus; no automated a11y audit |
| A29 | Logging without secrets | Pass | structlog, redacted tool args, no payload logging |
| A30 | Packaging and clean-machine install | Gap | Tauri scaffold + sidecar script; cannot build here (missing system libs), no clean-machine run |
| A31 | Cross-platform claims are tested | Gap | Linux dev only; Windows/macOS untested, documented |
| A32 | Honest status reporting | Pass | `docs/implementation-status.md` |
| A33 | Upgrade/uninstall/data-retention docs | Pass | `docs/installation.md` |
| A34 | License and third-party obligations | Pass with gap | proprietary license stated; dependency license audit not performed |
| A35 | No dead or fake compliance files | Pass | every doc maps to code; gaps are called out rather than padded |

## Highest-risk open items

1. A30/A31 — installer and cross-platform verification.
2. Live third-party integrations with real credentials (email/calendar/travel/broker).
3. A22 — explicit restart-resume test and A13 activation auditing.
