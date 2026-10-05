# myPA

A local terminal coding agent powered by Ollama. The default model is `qwen2.5-coder:7b`. It reads and edits projects, manages files and directories, executes commands and tests, and researches the web.

## Install everything

Download/copy this my-pa folder and run one command from it:

```bash
# Linux or macOS
bash install.sh
```

```powershell
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The bootstrap installs Python 3.10+ if missing, creates a private virtual environment, installs the Python package and dependencies, installs/starts Ollama if needed, downloads the selected local model if missing, and installs the `mypa` command on your user PATH. Open a new terminal afterward. Existing settings and downloaded models are reused. Default model: `qwen2.5-coder:7b`; use `bash install.sh --model NAME` or PowerShell `-Model NAME` to choose another.

Linux supports apt, dnf/yum, pacman, and zypper for missing system dependencies. macOS bootstraps Homebrew only if a suitable Python is unavailable. Windows reuses Python, uses winget when available, or downloads the Python installer directly. Ollama is installed through its [official platform installers](https://ollama.com/download). Internet access, sufficient disk/RAM for the model, and OS authorization for missing system packages are required. GPU drivers remain managed by the OS. Windows/macOS must meet [Ollama's supported-system requirements](https://docs.ollama.com/installation).

`bash install.sh --dry-run` previews the installation without changing anything. For isolated or managed installs, `python3 install.py --prefix PATH --bin-dir PATH --no-path` chooses destinations and avoids shell-profile changes. Installer sources live in per-user versioned releases; rerunning the installer refreshes the package while retaining configuration. The installer can be rerun after a failed dependency download.

## Start

```bash
mypa
mypa --workspace /path/to/project
mypa agent "Inspect this project and explain its structure"
mypa agent --workspace /path/to/project "Fix the failing tests"
```

The workspace defaults to the current directory unless your configuration overrides it. Model responses and task decisions come from the selected local Ollama model. The terminal shows live progress, tool outcomes, a final response, and elapsed time. `/tools` shows full results from the most recent task. Preliminary model replies are withheld until the tool loop finishes.

## Terminal controls

| Control | Action |
| --- | --- |
| `/help` | Show commands |
| `/clear` | Clear terminal screen and keep conversation |
| `/clearsession`, `/new` or `/reset` | Clear conversation, tool results, and input history; keep model and workspace |
| `/workspace PATH` | Switch project and clear conversation |
| `/models` | List installed local models |
| `/model NAME` | Select a local model for this session |
| `/status` | Show model, workspace, and context |
| `/tools` | Inspect the last task's tool results |
| `/stats` | Show model loading, prompt processing, generation speed, and tool time |
| `/doctor` | Diagnose Python dependencies, configuration, Ollama, model, and workspace |
| `/repair` | Repair missing Python dependencies, start local Ollama, and pull a missing model |
| `/evolve REQUEST` | Develop a tested improvement to myPA with the selected local model |
| `/rollback` | Undo the last source improvement if later edits have not changed it |
| `/paste` | Enter multiple lines; finish with a single `.` |
| `/exit` | Quit |
| Ctrl+C | Cancel the active model request or multiline input |
| Up / Down | Recall input where Python readline is available |
| Tab | Complete slash commands where readline is available |

Colors and animated progress work in terminals. Redirected output stays plain; set `NO_COLOR=1` to disable colors. Conversation and tool summaries remain in memory for the session. `/new` resets conversation context. Ctrl+C during a shell command stops its process group on Linux; changes already made by a command remain.

## Configuration

Global settings live in `~/.config/mypa/mypa.jsonc` (or `$XDG_CONFIG_HOME/mypa/mypa.jsonc`). A `mypa.jsonc` in the current directory overrides global settings. The example config documents the local settings.

```bash
mypa config --show
mypa config --set-default local/qwen2.5-coder:7b
mypa rules --list
mypa rules --add shell "rm *" deny
```

Defaults use 4096 context tokens, 1024 output tokens per step, and 16 tool steps. Ollama retains the model for five minutes. Keep context modest on machines with limited RAM. If Ollama disconnects, check `journalctl -u ollama -n 30`; `oom-kill` means the machine ran out of memory.

File tools stay inside the workspace and protect `.git`, `.aws`, `.agents`, and `.codex`. Shell commands run with your account's access and use the project's virtual environment when available. Commands time out after 60 seconds. Deletion requires a user request; nonempty directory deletion requires an explicit recursive flag. The tool log records actual execution. A step limit or failed tool is reported without claiming success.

## Development

Python 3.10+ and `requests` are required. Ollama must be running with the selected model installed.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

The package contains only the terminal agent, local conversation validation, tools, configuration, permission controls, and tests. Web UI, desktop UI, cloud adapters, and legacy installers have been removed.

Performance improvements reuse the Ollama connection across tool rounds, shorten repetitive instructions, and avoid decoding files without search matches. All tool schemas, model selection, context size, output limits, permission checks, and conversation controls remain available. `/stats` reports actual timing returned by Ollama; generation speed depends on your CPU and available memory.

## Self-repair and development

```bash
mypa doctor
mypa doctor --fix
mypa evolve "Improve error messages without changing existing commands"
mypa rollback
```

The same features are available inside the terminal as `/doctor`, `/repair`, `/evolve REQUEST`, and `/rollback`. Repair preserves invalid configuration instead of silently resetting it; it reports what needs correction. It never changes your selected model to a different model. Missing Python dependencies are installed only in the application virtual environment.

Self-development uses your selected local model to edit a temporary copy of the agent. It checks Python syntax, runs the original tests and the candidate tests, and checks the CLI before applying changes. Existing test files cannot be deleted. Before application it checks for concurrent source edits, makes a complete source backup, and restores it if file application fails. Restart mypa after applying or rolling back code. Configurations, virtual environments, model files, and project files are excluded from source backups and application.

Packaging/dependency changes require rerunning the installer and are rejected by the live self-development path. Tests provide regression protection, not proof that every model-generated change is correct. The model's shell tools run with your user access as in ordinary agent mode; the staged directory is not an OS sandbox. Failed/cancelled staging is discarded. Self-development is invoked explicitly, rather than running an endless unattended rewrite loop.

Recurring known tool errors also produce bounded, persistent repair hints that the agent uses on later tasks. Only fixed hint identifiers are stored, never raw commands, file contents, or user prompts. This improves tool use; it does not retrain model weights. Backups and hints live under `$XDG_DATA_HOME/mypa` or `~/.local/share/mypa` on Unix and `%LOCALAPPDATA%/mypa` on Windows. A crashed maintenance process can leave a lock file; its error identifies the file to remove after checking that no maintenance is active.
