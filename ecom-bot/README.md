# E-commerce AI Support Assistant

Production-oriented AI support chatbot for e-commerce: multi-agent orchestration (LangGraph),
RAG over store policies (PostgreSQL + pgvector), provider-independent LLM layer
(Claude/OpenAI/Gemini/Ollama), streaming chat (SSE), feedback collection, and Jira/ServiceNow
escalation.

> **Status:** under active build — see `TASKS.md` for the current task ledger and
> `IMPLEMENTATION_PLAN.md` for the execution sequence. Full setup/run documentation lands in
> TASK-044; the quickstart below reflects what works today.

## Quickstart (current)

```bash
cp .env.example .env          # fill in secrets; defaults work for mock mode
make install                  # uv sync (creates .venv + uv.lock)
make db-up                    # PostgreSQL 16 + pgvector on host port 5434
make migrate                  # alembic upgrade head
make run                      # API on http://localhost:8000
```

- API docs (once running): `http://localhost:8000/docs`
- Health: `GET /health` · Readiness: `GET /ready`

## Quality gates

```bash
make check                    # lint + format-check + typecheck + tests
```

## Documentation

| Doc | Purpose |
| --- | --- |
| `requirement.md` | Functional/non-functional/security requirements |
| `TASKS.md` | Task ledger with statuses and acceptance results |
| `IMPLEMENTATION_PLAN.md` | Execution sequence, quality gates, risks |
| `ARCHITECTURE.md` | Components, workflows, decisions (ADRs) |
| `docs/` | Detailed runbooks (added as tasks complete) |

## License

Proprietary.
