# E-commerce AI Support Assistant

Production-oriented AI support chatbot for e-commerce: multi-agent orchestration (LangGraph),
RAG over store policies (PostgreSQL + pgvector), provider-independent LLM layer
(Claude/OpenAI/Gemini/Ollama), streaming chat (SSE), feedback collection, and Jira/ServiceNow
escalation.

> **Status:** Build complete per `TASKS.md`. See `requirement.md` for requirements, `ARCHITECTURE.md` for design, and `TASKS.md` for the full task ledger.

## Quickstart

```bash
cp .env.example .env          # fill in secrets; defaults work for mock mode
make install                  # uv sync (creates .venv + uv.lock)
make db-up                    # PostgreSQL 16 + pgvector on host port 5434
make migrate                  # alembic upgrade head
make run                      # API on http://localhost:8000
```

Or with Docker: `cp .env.example .env && make up && make migrate-docker` (API on `http://localhost:8010`).

- API docs: `http://localhost:8000/docs` (or 8010 in Docker)
- Health: `GET /health` · Readiness: `GET /ready` · Metrics: `GET /metrics` (Prometheus)
- Streaming: `POST /api/v1/chat` with `stream=true` returns SSE events (see `docs/streaming.md`)
- Auth: JWT Bearer tokens (see `docs/auth-and-rate-limiting.md`). Mock mode requires no provider keys.

## Quality gates

```bash
make check                    # lint + format-check + typecheck + tests (821 passed)
make evaluate-all             # RAG + routing/tool-selection baselines
```

## API surface (v1)

| Endpoint | Purpose |
| --- | --- |
| `POST /api/v1/chat` | Chat turn (JSON or SSE streaming); enforces authz/guardrails/rate limits |
| `GET/DELETE /api/v1/conversations` | List/delete conversations |
| `GET/DELETE /api/v1/conversations/{id}` | Get conversation; enforces ownership |
| `GET /api/v1/conversations/{id}/messages` | Paginated history with tool executions |
| `POST/GET /api/v1/documents` | Ingest/list policy documents (pgvector) |
| `GET /api/v1/documents/{id}` | Get document details |
| `POST/GET /api/v1/feedback` | Submit/list feedback |
| `GET /api/v1/feedback/report` | Aggregated feedback report (requires `support:admin`) |
| `GET/POST /api/v1/tickets*` | Ticket lookup/refresh (ownership enforced) |
| `GET /health`, `/ready`, `/metrics` | Health/readiness/observability |

## Documentation

| Doc | Purpose |
| --- | --- |
| `requirement.md` | Functional/non-functional/security requirements |
| `TASKS.md` | Task ledger with statuses and acceptance results |
| `IMPLEMENTATION_PLAN.md` | Execution sequence, quality gates, risks |
| `ARCHITECTURE.md` | Components, workflows, decisions (ADRs) |
| `AGENTS.md` / `CLAUDE.md` | Agent instructions and rules |
| `docs/deployment.md` | Docker build/compose, production checklist, troubleshooting |
| `docs/auth-and-rate-limiting.md` | JWT auth, scopes, ownership, rate limiting |
| `docs/guardrails.md` | Input/output validation, PII/secret redaction, policies |
| `docs/streaming.md` | SSE event schemas and client examples |
| `docs/llm-providers.md` | Provider adapters, capability matrix, configuration |
| `docs/rag-pipeline.md` | Loading, chunking, embeddings, retrieval, grounding |
| `docs/commerce-adapter.md` | Commerce adapter interface and extension points |
| `docs/ticketing-adapter.md` | Ticketing adapter (mock/Jira/ServiceNow) |
| `docs/database-schema.md` | Schema overview |
| `docs/observability.md` | Metrics, tracing, evaluation |

## Known limitations

- **RAG eval baseline**: uses mock embeddings by default; abstention quality depends on embeddings. Run with a real embedding provider for accurate baselines.
- **Rate limiting**: in-process sliding window (per-instance). Use a distributed limiter in multi-replica deployments.
- **Providers**: mock provider is rejected in production. Real providers require API keys; unsupported capabilities fail loudly.
- **Ticketing**: `both` provider not yet implemented as a multi-backend coordinator.
- **Tracing**: LangSmith/OTel is opt-in and off by default.
- **Coverage**: 94% (see `make test-cov`).

## License

Proprietary.
