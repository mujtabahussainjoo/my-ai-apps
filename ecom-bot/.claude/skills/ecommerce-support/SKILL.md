---
name: ecommerce-support
description: Use when building or modifying customer-support features in this repo — chat/conversation endpoints, resolution workflow, feedback, or Jira/ServiceNow escalation. Load for any task touching TASKS.md phases 6-8.
---

# Skill: E-commerce Support Development

## When to load
Working on workers (order/product/account/resolution/escalation/feedback), the resolution
state machine, ticketing, feedback endpoints, or chat conversation flows.

## Ground rules
1. Read the active task row in `TASKS.md` first; implement only that task.
2. Requirements are authoritative: map new behavior to FR-/SEC-/ACC- ids in `requirement.md`.

## Resolution workflow (canonical)
- States: `OPEN → IN_PROGRESS → AWAITING_CUSTOMER → RESOLVED`; unresolved:
  `→ ESCALATION_PENDING → TICKET_CREATED`; failure: `TICKET_CREATION_FAILED`
  (`ARCHITECTURE.md` §4).
- Only `workflows/resolution.py` / `workflows/ticket_lifecycle.py` validate transitions.
- After every answer: ask "did this resolve it?" — never assume resolution.

## Ticketing checklist (before marking any escalation task DONE)
- [ ] Idempotency key = `conversation_id + issue_fingerprint`, persisted; duplicate create
      returns the existing ticket.
- [ ] `TICKET_CREATED` emitted only after the adapter's confirmed success response.
- [ ] Payload redacted: no credentials, payment data, unnecessary PII, internal reasoning
      (`requirement.md` FR-050/051).
- [ ] Failure path: escalation preserved, honest error to customer, retry available.
- [ ] Security test for duplicate submission + forged identifiers.

## Customer-data checklist (order/account work)
- [ ] Ownership check inside the tool/service, not in prompts.
- [ ] Cross-customer access → not-found/forbidden without leaking existence where applicable.
- [ ] Never invent price, stock, or order state — adapter data only or abstain.

## Definition of done
Tests (`tests/unit`, `tests/security`) green for the flow + `make lint typecheck` +
`TASKS.md` row updated with results and limitations.
