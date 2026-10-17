#!/usr/bin/env bash
# Claude Code PreToolUse hook: fast, deterministic pre-edit check.
# Args: $1 = colon-separated list of file paths being written/edited (CLAUDE_FILE_PATHS).
# Behavior:
#   - Only acts on Python files under src/, tests/, scripts/, alembic/.
#   - Runs `ruff check --fix` on those paths (fast, local, no network).
#   - Exit 2 = block the edit with feedback; exit 0 = allow.
# Failure handling: tooling errors (ruff missing) fail open with a warning so the
# hook can never wedge a session; lint violations block with the ruff report.
set -uo pipefail

paths="${1:-}"
[ -z "$paths" ] && exit 0

IFS=':' read -r -a files <<< "$paths"
py_files=()
for f in "${files[@]}"; do
  case "$f" in
    src/*.py|tests/*.py|scripts/*.py|alembic/*.py) [ -f "$f" ] && py_files+=("$f") ;;
  esac
done
[ ${#py_files[@]} -eq 0 ] && exit 0

# Project root = this script's location (scripts/hooks/ → repo root two levels up).
# NOTE: the git toplevel is the *parent* multi-project repo — never cd there.
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 0
cd "$root" || exit 0
if ! command -v uv >/dev/null 2>&1; then
  echo "precheck: uv not found; skipping lint (warning)" >&2
  exit 0
fi

out="$(uv run ruff check --fix "${py_files[@]}" 2>&1)"
status=$?
if [ $status -ne 0 ]; then
  echo "Ruff lint failed for edited files — fix before continuing:" >&2
  echo "$out" >&2
  exit 2
fi
exit 0
