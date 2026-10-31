# Installation

## End users

One-click installers live in `install/` (Linux, Windows, macOS) and a built Ubuntu package is
at `dist/NexaPilot AI_0.1.0_amd64.deb`. The package ships the webview UI plus a
PyInstaller-built backend sidecar (`nexapilot-server`); the shell starts it on
`127.0.0.1:8765` and stops it on exit. See `INSTALL.md` for double-click instructions.

System requirements (targets): Windows 10/11 x64; Ubuntu 22.04/24.04 x64 with
`libwebkit2gtk-4.1-0` and `libgtk-3-0` (declared as package dependencies, so `apt` installs
them). macOS is architecturally supported but untested.

The app icon (navy compass + paper plane) is generated from
`desktop/src-tauri/icons/icon-source.png` and embedded in the `.deb`, NSIS installer, `.dmg`,
launcher, and window. Regenerate with `cd desktop && npx tauri icon src-tauri/icons/icon-source.png -o src-tauri/icons`.

Local data lives in the platform data directory (`NEXAPILOT_DATA_DIR` overrides it):

| Platform | Default location |
| --- | --- |
| Linux | `~/.local/share/nexapilot` |
| Windows | `%APPDATA%\nexapilot` |
| macOS | `~/Library/Application Support/nexapilot` |

Contents: `nexapilot.db` (conversations, approvals, accounts metadata, audit),
`checkpoints.db` (LangGraph runs), `config/settings.json` (UI overrides), `secrets.json` only when
the secret backend is degraded, and `logs/`.

**Upgrade:** migrations run automatically on startup (`alembic upgrade head` semantics).
Back up the data directory first if you have valuable history.

**Uninstall / data retention:** delete the application, then delete the data directory to
remove conversations, accounts metadata, and settings. Secrets may also exist in the OS
credential vault under the service name `nexapilot`; remove them from the platform
credential manager (or `secret-tool clear service nexapilot <ref>` on Linux). Uninstalling
does not revoke Google OAuth grants — revoke those at <https://myaccount.google.com/permissions>.

## Developer setup

Prerequisites:

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node 20+ and npm
- For the desktop shell only: Rust stable (`rustup`), plus the Tauri Linux prerequisites:
  `sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev patchelf`
  (or run `npx tauri info` in `desktop/` for the authoritative list)

```bash
cd backend  && uv sync
cd ../frontend && npm install
cd ../desktop && npm install
```

Run:

```bash
# terminal 1
cd backend && uv run nexapilot

# terminal 2
cd frontend && npm run dev

# or the full desktop shell (starts Vite + reuses/starts the backend)
cd desktop && npm run dev
```

Environment configuration: copy `.env.example` to `backend/.env` (or export variables) and
fill only what you use. `NEXAPILOT_DATA_DIR` keeps experiments isolated.

### Packaging the backend sidecar

```bash
cd backend && uv sync --extra packaging
cd ../desktop && bash scripts/build-sidecar.sh
```

The script writes `desktop/src-tauri/binaries/nexapilot-server-<target-triple>`. Tauri
expects sidecars named this way when you add the `externalBin` entry; the current shell also
accepts a plain `nexapilot-server` next to the executable and `NEXAPILOT_BACKEND_BIN` for
custom layouts.

### Troubleshooting

| Problem | Fix |
| --- | --- |
| `tauri info` reports missing webkit2gtk/rsvg2 | install the dev packages above; without root you cannot build the shell |
| `keyring` errors at startup | expected on headless hosts; the app falls back to the `0600` file store and reports `degraded` |
| Port 8765 already in use | the desktop shell reuses the running backend; for manual runs set `NEXAPILOT_PORT` |
| Frontend shows network errors | backend not running, wrong port, or `NEXAPILOT_API_TOKEN` set without the UI token (Settings → API token) |
| Ollama not reachable | start `ollama serve`, pull the model, and set the base URL in Settings |
