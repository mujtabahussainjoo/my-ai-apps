# Rule: Testing

Scope: `tests/` and test tooling config.

- Framework: `pytest` + `pytest-asyncio` (`asyncio_mode = auto`). Layout:
  `tests/unit`, `tests/integration` (marker `integration`), `tests/security`
  (marker `security`), `tests/e2e` (marker `e2e`).
- **Zero credentials, zero network** in the default suite. LLM, commerce, and ticketing are
  mock adapters. Integration tests target local Postgres from `make db-up` and skip cleanly
  with a clear reason when it is absent.
- One behavior per test; name it for the behavior (`test_cross_customer_order_access_denied`),
  not the implementation.
- Assert on contracts and security properties (status codes, redaction, absence of leakage),
  not on incidental strings.
- Fixtures: build small factories in `tests/conftest.py` (users, conversations, products,
  orders). Do not depend on seed data ordering.
- Streaming tests consume the SSE parser and assert full event lifecycle order
  (`message_start → token* → … → message_end`) plus persistence afterward.
- Coverage: `make test-cov`; critical paths (guardrails, authz, ticket idempotency, RAG
  abstention) must be covered before marking related tasks DONE.
- Never weaken an assertion to get green; fix the code or record a limitation in `TASKS.md`.
