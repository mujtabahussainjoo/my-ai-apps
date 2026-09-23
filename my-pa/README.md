# myPA — your Personal AI (OpenCode-compatible wrapper)
# Cross-platform: Windows / Ubuntu / macOS
# Python-first so it runs without Node. Web + CLI + Desktop(Electron stub).

myPA is NOT a byte-for-byte fork of OpenCode (that repo is thousands of
files and moves fast). It is a branded distribution layer:

* reuses upstream `opencode` when installed (does not vendor it)
* provides `mypa` CLI, Web settings UI, and Desktop wrapper
* default model = opencode Zen free model (enabled out of box)
* optional OpenAI / Anthropic / local (Ollama) providers
* installer ALWAYS asks before installing Python components or local models

## Layout

```
myPA/
  Setup-myPA.bat             # Windows: DOUBLE-CLICK to install
  Setup-myPA.sh              # Ubuntu: double-click (Run as Program) or sh Setup-myPA.sh
  setup_win.py               # Windows guided setup (env check, launchers, shortcuts)
  setup_wizard.py            # interactive installer, permission-first
  install.ps1                # Windows installer steps
  install.sh                 # Ubuntu / macOS installer steps
  mypa.desktop               # Ubuntu desktop icon template
  build_deb.sh               # Ubuntu optional .deb builder
  pyproject.toml
    __init__.py
    __main__.py
    cli.py
    config.py
    providers.py
    server.py
    installer.py
  web/
    index.html             # chat + looks customization
    settings.html          # keys + provider config
    styles.css
    app.js
  desktop/
    package.json           # Electron wrapper (needs Node, optional)
    main.js
  mypa.example.jsonc
  README.md
```

## Install (double-click)

**Windows:** double-click `Setup-myPA.bat`. It checks for Python 3.10+,
then runs `install.ps1`: pip install (asks), setup wizard with local-model
choice (asks, never silent), `mypa.bat` launcher + Start Menu/Desktop
shortcuts (asks).

**Ubuntu:** double-click `Setup-myPA.sh` (right-click -> Run as Program)
or run `sh Setup-myPA.sh`. It runs `install.sh`: pip install (asks),
wizard (asks), `~/.local/bin/mypa` launcher (asks), desktop icon (asks).
Optional installable package: `sh build_deb.sh` -> `sudo dpkg -i ...deb`.

## Quick start (manual, no Node needed)

```powershell
cd myPA
python -m pip install -e .
python setup_wizard.py     # asks before anything is installed
python -m mypa --help
python -m mypa --web       # open http://127.0.0.1:3210
```

Ubuntu / macOS:

```bash
cd myPA
pip3 install -e .
python3 setup_wizard.py
python3 -m mypa --web
```

## Settings

Config resolution (later overrides earlier):
1. `~/.config/mypa/mypa.jsonc` (global)
2. `./mypa.jsonc` (project)

Edit via Web UI `/settings.html` or by hand. Keys are stored as
`{env:VAR_NAME}` references where possible — never hardcode secrets.

Default enabled provider:
`opencode/muse-spark-1.3-contributor-free`
