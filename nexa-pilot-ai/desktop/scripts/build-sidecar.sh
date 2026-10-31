#!/usr/bin/env bash
# Build the standalone backend used as the Tauri sidecar.
#
# Requires PyInstaller (installed into the backend venv on demand) and a rust
# target triple so Tauri can find the binary.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
triple="${TAURI_TARGET_TRIPLE:-$(rustc -vV | sed -n 's/^host: //p')}"
out_dir="$repo_root/desktop/src-tauri/binaries"
mkdir -p "$out_dir"

cd "$repo_root/backend"
uv sync --extra packaging
uv run pyinstaller \
  --noconfirm \
  --clean \
  --name nexapilot-server \
  --onefile \
  --collect-all langgraph \
  --collect-all langchain_core \
  --collect-submodules keyring \
  --collect-submodules uvicorn \
  --collect-submodules alembic \
  --add-data "$repo_root/backend/alembic:alembic" \
  --add-data "$repo_root/backend/alembic.ini:." \
  --hidden-import aiosqlite \
  --hidden-import icalendar \
  --distpath "$out_dir/tmp" \
  --workpath "$out_dir/work" \
  --specpath "$out_dir" \
  src/nexapilot/__main__.py

mv "$out_dir/tmp/nexapilot-server" "$out_dir/nexapilot-server-$triple"
rm -rf "$out_dir/tmp" "$out_dir/work" "$out_dir/nexapilot-server.spec"
echo "Sidecar written to $out_dir/nexapilot-server-$triple"
