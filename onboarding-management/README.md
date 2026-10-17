# BetterUp Onboarding Integration - Prototype

A small, working prototype that safely propagates employee hiring/changes across systems, validates before spreading data, handles failures and retries, tracks exceptions and onboarding deadlines.

## What it demonstrates

- **Receive → Normalize → Validate**: Accepts Ashby and approved off-cycle (`workday_intake`) events, normalizes to a common model, runs deterministic validation.
- **Safety gate**: Field ownership rules, allowed locations, date validation, duplicate detection, cross-system consistency. Disputed updates are blocked; unrelated updates may still proceed.
- **Idempotency**: Operation ledger keyed `employee_id|event_id|target|operation`; replays return `SKIPPED_IDEMPOTENT` with no duplicate side effects.
- **Propagation & verification**: Changed fields mapped to affected systems; each target is updated and verified independently.
- **Resilience**: Classifies failures (temporary/permanent/unknown); bounded retries with exponential backoff; timeout outcomes are reconciled against the target. Successful targets are never rolled back.
- **Exceptions & AI assistance**: Exceptions are persisted with reason, conflicting values, and advisory AI recommendations (`recommended_action`) from a strict JSON schema. AI is advisory-only and falls back deterministically if unavailable.
- **Audit trail**: Structured JSONL logging (`data/audit_log.jsonl`) covering timestamps, previous/new values (sensitive fields masked), validation results, per-target attempts/status, errors, and exceptions.
- **Deadline monitoring**: Tracks hardware, background check, and Okta tasks; warns when approaching (within 7 days), flags overdue, enforces a per-task reminder cadence to avoid duplicates.
- **Dashboard + read-only copilot**: A server-rendered web UI to run scenarios, inspect exceptions, the audit trail, tasks and the operation ledger, resolve exceptions (human-in-the-loop) and ask an AI chat agent about the current state. The agent is advisory/read-only and falls back deterministically without an API key.

## Architecture

```text
sample_events/        # Sample Ashby/off-cycle events, authoritative records, tasks
app/                  # Core workflow: models, config, normalizer, validator,
                      #   authoritative_store, dependency_mapper, event_receiver,
                      #   idempotency_store, retry_handler, exception_handler,
                      #   ai_helper, chat_agent, audit_logger, deadline_monitor,
                      #   task_store, targets
adapters/             # HTTP adapter to the local demo portal
demo_portal/          # FastAPI mock simulating 3rd-party systems + fault injection
web/                  # Server-rendered dashboard (Jinja) + JSON APIs + chat agent
tests/                # Pytest scenarios (the 5 required demos + AI + monitor + web)
run_demo.py           # End-to-end demo runner (in-process)
data/                 # Runtime stores (created on first run: .json/.jsonl)
```

## Quickstart

1. **Install deps** (already done in venv if following steps):

   ```bash
   cd onboarding-management
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment** (optional). Copy `.env.example` to `.env`. If you leave `OPENAI_API_KEY` empty, the AI exception classifier uses deterministic fallback.

   ```bash
   cp .env.example .env
   # OPENAI_API_KEY=sk-...  # optional
   ```

3. **Run the end-to-end demo (in-process, no server needed)**:

   ```bash
   .venv/bin/python run_demo.py
   ```

4. **Run the test suite**:

   ```bash
   .venv/bin/python -m pytest
   ```

5. **Run the mock demo portal separately (live mode)**:

   ```bash
   # terminal 1
   .venv/bin/python -m demo_portal.main
   # terminal 2
   .venv/bin/python run_demo.py --live
   ```

6. **Open the dashboard (web UI + read-only copilot)**:

   ```bash
   .venv/bin/python -m web.main
   # then open http://127.0.0.1:8090/
   ```

   The dashboard runs the demo portal in-process, so no second server is
   needed. Set `WEB_LIVE=1` to talk to a separately-running demo portal at
   `DEMO_PORTAL_URL`. Use **Reset demo** to clear the ledger, exceptions,
   audit log and tasks before re-running scenarios.

## Demo scenarios (verified)

- **A. Valid new hire**: All systems updated; each verified independently → `COMPLETED`.
- **B. Location conflict**: Cross-system conflict blocks unsafe updates; exception persisted with `human_review` recommendation → `NEEDS_REVIEW`.
- **C. Equipment timeout/transient failure**: Temporary failure retries with backoff; unknown timeout reconciled to success if already applied; persistent failure → `PARTIALLY_COMPLETED` + escalated exception.
- **D. Off-cycle hire**: `workday_intake` uses the same workflow → `COMPLETED`.
- **Duplicate event**: No duplicate side effects; all targets `SKIPPED_IDEMPOTENT`.
- **AI unavailable**: Core validation, propagation and exceptions still work (deterministic fallback).
- **Deadline monitoring**: Approaching and overdue tasks flagged; deduplicated by cadence; closed tasks ignored.

## Dashboard and read-only copilot

`web/` is a thin FastAPI + Jinja UI over the same collaborators the demo uses. It has no build step and no extra servers. Each third-party system from the brief gets its own named tab (`app/systems.py` holds the catalog of real names/roles shared with the UI):

- **Overview**: live cards (open exceptions, overdue/due-soon tasks, failed operations, idempotent skips) and one-click buttons to run each demo scenario.
- **Ashby · Workday · Okta/Lumos · Google Workspace · Slack · Equipment/ExpoIT · Onboarding cohort tracker**: one tab per system, showing its role, connection status and the mock records/events it currently holds (propagations land here and are read back).
- **AI copilot**: status (OpenAI vs deterministic fallback), the allowed recommendation actions, the exception classifications so far, and the chat agent.
- **n8n / Zapier**: shown for completeness; the prototype orchestrates itself, so it reports "not used".
- **Exceptions**: every open/resolved exception with its field, conflicting values, AI recommendation and an inline human resolution form.
- **Audit trail**: newest-first workflow and exception entries, sensitive fields masked upstream.
- **Tasks & deadlines**: the tracker plus the monitor's approaching/overdue view and a "Run deadline monitor" button (read-only preview never triggers reminders).
- **Operation ledger**: the idempotency rows keyed `employee | event | target | operation`.

Result tables, the ledger and the audit log render real system names (Workday, Google Workspace, ...) instead of raw keys, from the same `sys_names` map the UI uses.

The copilot (`app/chat_agent.py`) is **advisory and read-only**: it only reads a compact snapshot of the dashboard state and can never propagate a change, resolve an exception or bypass validation. With `OPENAI_API_KEY` set it uses the model; otherwise a deterministic keyword responder answers from the same context, so the feature works offline. JSON APIs (`/api/summary`, `/api/exceptions`, `/api/audit`, `/api/tasks`, `/api/ledger`, `/api/scenarios/{key}`, `/api/chat`, `/api/monitor/run`, `/api/reset`) are usable independently of the UI.

## Data files (runtime)

- `data/idempotency_ledger.json` — operation outcomes by key
- `data/exceptions.json` — open/resolved exceptions
- `data/audit_log.jsonl` — chronological audit entries
- `data/cohort_tracker.json` — onboarding tasks (mirrors cohort tracker)
- `sample_events/` — sample inputs and authoritative records used for the demo

## Notes on the "demo portal of local"

The "demo portal" is a local FastAPI app (`demo_portal/`) that simulates the third-party systems (Workday, Okta, Google Workspace, Slack, Equipment, Cohort Tracker). Adapters call it over HTTP via `DemoPortalClient`. Tests run it in-process via `httpx.TestClient` (no real network). Faults (`temporary`, `rate_limit`, `permanent`, `timeout`) are injected at `/ _admin/faults` to exercise retry/reconciliation. This matches "use demo portal of local" as requested.
