# CLAUDE.md — Claude Code Project Instructions

This file is Claude Code's project entry point. Portable rules live in **`AGENTS.md`** — read
it first and obey it. This file only adds Claude Code–specific conventions.

## Session policy

1. On session start: read `AGENTS.md`, `TASKS.md`, and the current task's row. Resume exactly
   where the ledger says — typically the task marked `IN_PROGRESS`.
2. Work **one primary task** per cycle: implement → verify → update `TASKS.md` → summarize.
   Never start the next task without recording the current one's results.
3. Ask the human only when a decision is genuinely blocking; otherwise pick a sensible
   default and document it in `TASKS.md`.
4. After each task, report: files created/changed, commands run, results, next task.

## Claude Code specifics

- Project settings: `.claude/settings.json` (permissions only — no secrets, no globally
  disabled checks). Modular rules: `.claude/rules/*.md`. Skills: `.claude/skills/*/SKILL.md` —
  load the relevant skill when starting RAG, agent, or support-domain work.
- Hooks (if configured in `.claude/settings.json`) run `scripts/hooks/precheck.sh`: fast
  `ruff check` on staged files. If the hook fails, fix the lint errors before continuing.
  Hooks must stay fast (<10 s) and deterministic; never block on network or DB.
- Prefer tool use in this order for code changes: read neighboring modules → edit →
  `make lint typecheck` → targeted `uv run pytest tests/<area>` → full `make test` before
  marking a task DONE.

## Claude Code vs other agents

- `CLAUDE.md` + `.claude/*` are Claude Code conventions. OpenCode/Cursor agents use
  `AGENTS.md` (and their own config). If you change a rule that matters to both, update
  `AGENTS.md` and mirror the change here — never diverge the substance.

## Commands

Same as `AGENTS.md` (`make install|run|db-up|migrate|seed|lint|typecheck|test|check`).
Do not invent shorter paths; use the Makefile targets so docs stay truthful.

## Security reminders (Claude Code sessions)

- Never read or print `.env` contents; use `.env.example` as the reference.
- Never commit credentials, and never `git add` anything outside this project folder in the
  parent repo.
- When writing tests for authz/injection/PII, follow `SEC-*` ids in `requirement.md` so
  coverage is traceable.
