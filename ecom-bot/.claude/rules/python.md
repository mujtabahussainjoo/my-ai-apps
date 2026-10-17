# Rule: Python style and typing

Scope: all `.py` files under `src/`, `tests/`, `scripts/`, `alembic/`.

- Target Python 3.12. Use modern syntax (`X | None`, `match` where it helps, dataclasses for
  plain records).
- **mypy `--strict` is on**: annotate every public function, no `Any` leakage into public
  signatures, no `type: ignore` without a cited reason.
- Formatting/lint is `ruff format` + `ruff check` (rules E,W,F,I,UP,B,SIM,RUF,ASYNC,C4,PTH,T20
  per `pyproject.toml`). Never disable a rule globally to make a task pass; use a narrow
  per-file ignore with justification.
- Async correctness: no blocking I/O in the event loop (use `httpx.AsyncClient`, async
  sessions); never call `.result()`/`asyncio.run()` inside request handlers.
- Errors: raise typed exceptions from `core/exceptions.py`; map to HTTP in the API layer only;
  no bare `except:`; log with context, not with secrets.
- Imports: stdlib → third-party → local, enforced by ruff isort. Circular imports are a design
  smell — fix layering instead of local imports.
- No `print()` in `src/` (ruff T20); use structured logging.
