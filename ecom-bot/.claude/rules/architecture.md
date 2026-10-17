# Rule: Architecture and layering

Scope: module placement, dependencies, and orchestration decisions.

- Package layout is fixed: `api/ core/ schemas/ llm/ agents/ rag/ tools/ guardrails/
  integrations/ db/ services/ workflows/` (see `ARCHITECTURE.md` §2 for responsibilities).
  Do not add new top-level modules without updating `ARCHITECTURE.md` + `TASKS.md`.
- **Dependency direction**: `api → services → workflows/agents(workers) → tools →
  integrations/db`. Lower layers never import upper layers. `schemas/` and `core/` are
  leaf-ish and importable from anywhere.
- **Framework firewall**: LangChain/LangGraph imports only in `llm/`, `agents/`,
  `rag/retrieval.py`. Workers/services/tools must be plain Python (testable without
  framework runtime). If a worker needs a model call, depend on the `llm.base` interface.
- **One store, adapters outward**: PostgreSQL+pgvector is the system of record for
  conversations/RAG/tickets; live commerce data comes from the commerce adapter (never from
  mock DB rows in production paths). Ticketing = adapter selected by config.
- **Contracts**: every worker/tool has typed Pydantic input/output models in `schemas/`;
  ORM objects never cross into API responses or agent state.
- **State machines are central**: resolution/ticket transitions go through
  `workflows/` validators — agents may request transitions but cannot invent them.
- Streaming: only customer-visible content on the wire; internal reasoning never leaves the
  graph. Follow the event schema in `ARCHITECTURE.md` §6.
- Config changes require: `config/*.yaml` default → env override → validation in
  `core/config.py` → `.env.example` update → note in `TASKS.md`.
