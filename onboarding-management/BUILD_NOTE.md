# Build Note

## Why this slice?

I selected **change propagation with cross-system validation as a safety gate**. Changes after an offer (or off-cycle hires) can easily create inconsistent records across HR, identity, access, equipment and onboarding trackers. A single end-to-end workflow that:

1. Validates deterministically before propagating,
2. Maps changed fields to affected systems,
3. Tracks each target independently (preserving partial success),
4. Prevents duplicates and handles retries/reconciliation,

directly addresses the stated coordination and data-quality problem without over-engineering the entire suite.

## Key engineering choices

- **Common model first**: `StandardEmployee` normalizes heterogeneous incoming fields (source aliases) into canonical names. We never silently guess unknown values — bad dates/locations fail validation.
- **Explicit field ownership**: Cross-system validation defines which source may change which fields (e.g. Ashby has limited mutability; `workday_intake` can supply a full approved record). A disputed field blocks dependent targets but safe, unrelated updates still proceed.
- **Idempotency as a first-class concern**: Operation key `employee_id|event_id|target|operation`; `SKIPPED_IDEMPOTENT` on replay with `attempts=0`; ledger is persisted to JSON for the demo.
- **Separation of concerns**: `DemoPortalClient` does one attempt and classifies the outcome; `RetryHandler` owns bounded backoff and reconciliation (timeout → verify target presence); `Orchestrator` owns the pipeline.
- **Resilience & auditability**: Per-target results are independent; successful targets remain successful on partial failure. `AuditLogger` records previous/new values (PII masked), validation, attempts, error categories/messages and exception ids. `ExceptionHandler` persists open/resolved exceptions.
- **Safe AI integration**: `AIHelper` uses only minimal context (`exception_type`, `field_name`, short `reason`), validates against a strict schema (only allowed `recommended_action` values), and never mutates state or bypasses validation. If `OPENAI_API_KEY` is missing or the call fails, it deterministically falls back; the workflow continues to function without AI.
- **Local "demo portal"**: FastAPI mock at `demo_portal/` simulates all third-party systems with fault injection (`temporary`, `rate_limit`, `permanent`, `timeout`, `timeout` applies state then returns 504 for reconciliation). Adapters use it over HTTP; tests drive it in-process. This satisfies "for 3rd party port use demo portal of local".
- **Operator UI without build tooling**: `web/` is a server-rendered FastAPI + Jinja dashboard (plus small vanilla-JS/CSS assets). It is a thin, read-mostly view over the same orchestrator/stores, so there is nothing to compile and a single command starts it. The one mutating operator action is resolving an exception (human-in-the-loop), which is written to the audit trail; running a scenario or the deadline job is explicit and opt-in.
- **Named third-party systems everywhere**: `app/systems.py` is a single catalog of the systems from the brief (Ashby, Workday, Okta/Lumos, Google Workspace, Slack, Equipment/ExpoIT, cohort tracker, AI copilot, n8n/Zapier) with real display names, roles and kinds. The dashboard renders **one tab per portal** showing each system's live mock records/events read back from the demo portal; result tables, the ledger and audit use the same names instead of raw keys, and incoming events are dropped into the source system's inbox (`/ashby/events`) so the Ashby view reflects what was actually received.
- **Read-only copilot agent**: `app/chat_agent.py` answers operator questions about open exceptions, deadlines, failures and the audit trail. It receives only a compact, size-bounded snapshot, is advisory-only (cannot mutate state, resolve exceptions or bypass validation) and degrades to a deterministic keyword responder when no API key is present — mirroring the safety posture of `AIHelper`.
- **Testable & deterministic**: `RetryHandler.sleep` and `AIHelper` clients are injectable; stores use temp paths in tests; `pytest.ini` + fixtures keep tests isolated and repeatable.

## What I would productionize

- **Persistence**: Replace JSON files with a durable DB (e.g. Postgres) for operation ledger, audit log, exceptions and tasks; use an event store and outbox/retry queue for reliable delivery.
- **Real adapters**: Replace mocks with actual API clients using OAuth2/mTLS, circuit breakers, per-tenant rate limits, idempotency keys on outbound requests.
- **Security & privacy**: Secrets via a vault, least-privilege service accounts, field-level PII redaction (extend masking), audit access controls and retention policies.
- **Reliability**: Distributed idempotency (store key in a durable table), reconciliation jobs to catch drift, dead-letter queue for exhausted retries, alerting/metrics (SLI/SLOs).
- **Workflow & governance**: Approval flows for sensitive changes, a hardened human-in-the-loop UI for exception resolution (the prototype dashboard is a first cut - it needs SSO/authz, CSRF protection and audit of who viewed what), contract tests against real system stubs, canarying.
- **AI**: Evaluate providers/models, add rate limiting, prompt injection guardrails (already minimal), telemetry on recommendations vs human outcomes, and an allowlist of exception types the AI may classify.

## AI tools used

I used the **opencode** CLI (this agent) to implement the prototype end-to-end: scaffolded modules, wrote FastAPI demo portal + adapters, built validator/orchestrator, added retry/exception handling, AI helper, audit logger, deadline monitor, and the test/demo files. I later extended it the same way with the server-rendered dashboard (`web/`) and the read-only copilot (`app/chat_agent.py`), adding Jinja2 to the requirements and tests for both. The user explicitly asked to avoid Claude-specific references and to use the local demo portal / OpenAI key path.

**Example of a correction (concrete)**: During Task 7 the changed-field detection initially treated empty values as "changes" when comparing against authoritative records (e.g. `start_date_changed` also flagged `preferred_name`, `personal_email`, `manager` as changes). I tested with the authoritative seed (`EMP-101`) and saw Slack was being "affected". I corrected `compute_changed_fields()` to:

- Prefer the event's declared `changed_fields` (source tells us what changed),
- Then diff only where the incoming value is non-empty and differs from previous,
- Otherwise fall back to populated fields.

After the edit, `start_date_changed` correctly affected Workday/Okta/Google/Equipment/Tracker but not Slack (as per the dependency rules for `start_date`), and tests/`run_demo.py` matched expectations.

**How I verified the correction**: Ran a quick check printing `changed` for `start_date_changed` against `authoritative_records.json`, re-ran the orchestrator for that scenario, and confirmed the target list changed from 6 (including Slack) to 5 (excluding Slack). The fix is in `app/dependency_mapper.py` and is covered by the updated behavior in the demo/tests.

## The workflow to remember

**Receive → Normalize → Validate → Check idempotency → Identify affected systems → Update → Verify → Retry or escalate → Audit → Monitor deadlines → Close**

Core principle: **never assume one successful run means every system is correct. Track each operation, verify independently, and keep unresolved exceptions visible.**
