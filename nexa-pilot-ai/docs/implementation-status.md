# Implementation status

Last verified: 2026-10-29. Verification commands and results are at the bottom.

## Milestones

| Milestone | Status | Evidence / notes |
| --- | --- | --- |
| 0 — Audit and plan | Done | Repository contained only the workflow document; `docs/audit-checklist.md` authored because the referenced checklist was absent; gap matrix below |
| 1 — Desktop foundation | Partial | Full UI + backend lifecycle code exists; shell cannot be compiled here (no webkit2gtk/rsvg dev packages, no root). Config + dependency resolution verified with `npx tauri info` and `cargo generate-lockfile` |
| 2 — Provider abstraction | Done | 5 adapters, single active provider, connection tests, capability flags, normalized errors, streaming; activation refuses on failed test; no fallback |
| 3 — LangGraph agent core | Done | Typed state, deterministic router, bounded loop, Pydantic tool contracts, approval gate + resume, SQLite checkpoints |
| 4 — Research and coding | Done (live search untested) | Cited research prompt + source URL/timestamp handling; workspace-confined file tools, command allowlist, diffs, tests executed via allowlist |
| 5 — Email and calendar | Partial | Gmail/IMAP/SMTP + the full Google Calendar v3 resource surface (Acl, CalendarList, Calendars, Channels, Colors, Events, Freebusy, Settings) implemented with mock-transport tests; OAuth connect/sync not exercised against real Google accounts |
| 6 — Travel | Partial | Amadeus flights/hotels + rail guidance implemented; search is live-API dependent and untested with credentials; booking intentionally not implemented |
| 7 — Finance | Partial | Stooq/Yahoo quotes, portfolio, paper orders, capped+gated live orders via generic REST; no real broker account tested |
| 8 — Hardening and packaging | Partial | Security tests, audit trail, error contract, docs, branded icons, one-click install scripts; Linux `.deb` built; Windows NSIS bundle built and installed locally (unsigned, not clean-machine tested); macOS bundle outstanding; no code-signing certificate |

## What works end to end (locally)

- Settings: provider list/activate/test, settings PATCH with persistence, secret read/write/delete.
- Chat SSE: routing, token streaming, tool start/end, approvals, cancellation, persistence,
  activity history, conversation list.
- Tools: 59 tools (30 approval-gated); approval-required tools return `approval_required` and
  execute only after an argument-bound approval; side-effect-free tools run directly.
- Coding: read/write inside workspace, traversal/symlink rejection, allowlisted commands
  (pytest/ruff/mypy/npm/node/go/cargo/make/git read-only subset), diffs.
- Email/calendar: account listing, connect (OAuth start/callback, IMAP), sync; Google Calendar
  events (list/get/instances/create/update/patch/delete/move/quick-add/import), CalendarList,
  Calendars (create/update/patch/delete/clear/transfer), Acl, Colors, Freebusy, Settings and
  push-channel watch/stop. Every mutating or watch call is approval-gated; email
  send/forward/delete (gated) with multiple-account isolation.
- Research: Brave/Tavily/SearxNG search + SSRF-protected page fetch; citations in final answer.
- Finance: quotes with timestamps, portfolio summary, watchlist, paper/live order path with
  caps and approval.
- Desktop: Tauri 2 project, CSP restricted to loopback, backend reuse/spawn/kill lifecycle,
  PyInstaller sidecar (verified standalone), branded icon set (PNG/ICO/ICNS), one-click
  install/uninstall scripts for Linux, Windows, and macOS, and a built Ubuntu `.deb`.

## Honest gaps

1. **Installer is built but not clean-machine tested.** `NexaPilot AI_0.1.0_amd64.deb`
   (48.4 MB, bundles the UI and `nexapilot-server`) was produced with Tauri 2.12.5 on
   Ubuntu 24.04 using an extracted WebKitGTK/GTK sysroot (no root on the build host). The
   sidecar was run standalone and served `/api/health` with migrations applied. Launching
   the full window on this WSL host fails only because WebKit looks for
   `WebKitNetworkProcess` under the compile-time `/usr/lib` path; a normal Ubuntu install
   provides it. A Windows NSIS bundle was built and installed on a Windows 11 host
   (unsigned); its sidecar served `/api/health`. macOS is untested.
2. **No live third-party credentials.** Provider, Gmail, Google Calendar, Amadeus, and broker
   integrations are verified with mock transports/scripted providers. Real-world quirks
   (quota, regional availability, OAuth consent screens) are unverified. Google Calendar
   watch channels are stateless: the API returns the channel ID/resource ID but NexaPilot
   does not persist channels or run a public HTTPS webhook listener, so push notifications
   are not delivered yet.
3. **No Gmail history cursor.** Sync fetches the latest N messages and dedupes; it is bounded
   but not a full incremental sync.
4. **Travel is search/guidance only.** Booking and payments are intentionally not implemented.
5. **Live trading is a generic REST contract.** It requires a broker base URL and key, is
   capped, and gated, but only against the documented request/response shape — not a specific
   broker's sandbox.
6. **No code signing by default.** Windows builds accept `-CertificateThumbprint` or
   `-PfxPath` on `install/windows/install.ps1`, which makes Tauri sign the app, sidecar, and
   NSIS installer. Without a CA-issued certificate, SmartScreen still warns and Smart App
   Control still blocks. macOS is unsigned and untested.
7. **Audit coverage** is approval decisions and tool executions; provider activation changes
   are visible through settings state but not appended to `audit_log`.

## Verification

```
backend:  uv run ruff check src tests      -> All checks passed
          uv run ruff format --check       -> 80 files already formatted
          uv run mypy                      -> Success: no issues found in 70 source files
          uv run pytest                    -> 114 passed, 43 warnings
frontend: npm run typecheck                -> clean
          npm test -- --run                -> 10 passed
          npm run build                    -> built (295 kB JS, 15 kB CSS)
desktop:  npx tauri info                   -> config parsed
          cargo generate-lockfile           -> tauri 2.12.5 resolved
          npx tauri build --bundles deb     -> NexaPilot AI_0.1.0_amd64.deb (48.39 MiB)
          sidecar standalone                -> /api/health ok, migrations created nexapilot.db
          ldd desktop + sidecar             -> no missing libraries
```

Warnings are LangChain pending-deprecation notices from dependencies, not failures.
