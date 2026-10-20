# Ticketing adapter

Escalation talks to one external ticketing backend through a single interface so the agent layer
never depends on a provider SDK (FR-041/FR-044, INT-004). The interface and the v1 mock live in
`src/ecommerce_support/integrations/ticketing.py`.

## Contract

```python
class TicketingAdapter(ABC):
    provider: TicketProvider

    async def create_ticket(self, request: TicketRequest) -> ExternalTicket: ...
    async def get_status(self, external_id: str) -> ExternalTicket | None: ...
```

Rules:

- A ticket is reported as created **only** when the adapter returns a confirmed `ExternalTicket`
  (FR-044). Adapters must raise `TicketCreationError` (`code = "ticket_creation_failed"`) instead of
  returning a fabricated ticket, so the lifecycle can surface `TICKET_CREATION_FAILED` truthfully.
- Failure messages are safe to show a customer — never echo payload contents or credentials.
- Adapters are plain Python (no framework imports) and return Pydantic schemas, never ORM objects.

## Implementations

| Adapter | Status | Notes |
| --- | --- | --- |
| `MockTicketingAdapter` | Shipped (mock) | In-memory; deterministic. `fail_next=N` fails the next `N` calls then succeeds; `always_fail=True` simulates an outage. Successful tickets are retrievable via `get_status`. |
| `JiraTicketingAdapter` | Shipped (live) | Jira REST v2 (`POST /rest/api/2/issue`, `GET /rest/api/2/issue/{key}`), HTTP basic auth with an API token, config-driven; redacted payload via `build_jira_payload`. |
| ServiceNow | Shipped (live) | ServiceNow Table API (`POST /api/now/table/incident`, `GET /api/now/table/incident/{sys_id}`), HTTP basic auth, config-driven; redacted payload via `build_servicenow_payload`. |

Selection is via `create_ticketing_adapter(provider, config=…, client=…)` using
`config/app.yaml` → `integrations.ticketing_provider` (`mock | jira | servicenow | both | none`).
Jira requires `jira_base_url`/`jira_email`/`jira_api_token`/`jira_project_key`; ServiceNow requires
`servicenow_instance`/`servicenow_username`/`servicenow_password`. Missing values raise
`ConfigurationError`; `both` raises until the multi-backend coordinator lands (TASK-034); `none`
yields an always-failing mock so escalation failure paths remain testable.

### ServiceNow specifics

- **Payload** (`build_servicenow_payload`): `short_description`, `description`, `urgency`
  (`priority` → 1/2/3), plus `category="inquiry"`/`contact_type="self-service"`. The description is
  shared with Jira via `build_ticket_description` (redaction + escalation context).
- **Status mapping**: ServiceNow incident `state` → `TicketStatus` (`1`→`CREATED`, `2/3`→`IN_PROGRESS`,
  `6`→`RESOLVED`, `7/8`→`CLOSED`). Unknown states map to `IN_PROGRESS`.
- **Failure**: transport errors, non-2xx responses, or a create response without `result.sys_id`
  raise `TicketCreationError`; `get_status` errors raise `TicketingError`; a 404 returns `None`.
- Tests use `httpx.MockTransport`; no live ServiceNow is required.


### Jira specifics

- **Payload** (`build_jira_payload`): project/issuetype/summary/description/priority/labels. Free
  text is scrubbed by `guardrails.redaction.redact_text` (emails, cards, long digit runs, tokens,
  `sk-…`/bearer keys). Order id, product ids, expected/actual behavior, steps, and cited sources are
  appended to the description so the assignee has context without internal reasoning.
- **Status mapping**: Jira workflow status → `TicketStatus` (`new/open/to do`→`CREATED`,
  `backlog`→`PENDING`, `in progress/in review`→`IN_PROGRESS`, `done/resolved/closed`→`RESOLVED`).
- **Failure**: transport errors, non-2xx create responses, or a create response with no `key` raise
  `TicketCreationError` — a ticket is never reported created without a confirmed response.
  `get_status` transport/non-2xx errors raise `TicketingError`; a 404 returns `None`.
- Tests use `httpx.MockTransport`; no live Jira is required.


## Extension checklist (Jira/ServiceNow)

1. Implement `TicketingAdapter` in `integrations/`; set the `provider` class attribute.
2. Read credentials from `IntegrationsConfig` (env-overridable) — never hard-code or log secrets.
3. Build the external payload from `TicketRequest` through a redaction step (FR-050/FR-051): no
   credentials, payment data, unnecessary PII, or internal reasoning.
4. Map transport errors to `TicketCreationError` (creation) / `TicketingError` (status).
5. Register the provider in `create_ticketing_adapter` and add mocked-HTTP tests.

See `integrations/jira.py` for the reference implementation (config `from_config`, redacted payload,
status mapping, confirmed-only success, `httpx.MockTransport` tests).

## Escalation lifecycle (`services/tickets.py`)

`TicketService` owns the business rules around ticket creation and is framework-free:

- **State machine**: the conversation must be able to reach `ESCALATION_PENDING`; the service moves
  it there and then to `TICKET_CREATED` **only after** the adapter confirms creation. On failure it
  moves to `TICKET_CREATION_FAILED` and re-raises `TicketCreationError`, so the customer gets a
  truthful message while the escalation is preserved and a retry remains possible (ACC-005/ACC-006).
- **Idempotency**: a deterministic key (`escalation:{conversation_id}`) is derived when the caller
  does not supply one. A repeat call by key, or an existing non-failed ticket for the conversation,
  returns the stored ticket with `created=False` and **no** provider call (FR-043). The DB unique
  constraint on `idempotency_key` is the last line of defence.
- **Failure audit**: a `FAILED` attempt row is stored *without* the idempotency key so it never
  blocks a retry; audit events are `ticket.created` / `ticket.creation_failed` (provider + error
  code only — no payload text).
- **Status queries**: `refresh_status` re-reads provider state and updates the local record (FR-053).

