# myPA — Personal AI

myPA is a local coding and research agent powered by Ollama, with a web UI and terminal interface. The agent reads, creates, edits, moves and deletes files and folders, searches source code, runs commands and tests, searches the web through DuckDuckGo with a Bing RSS fallback, reads web pages, and searches Wikipedia. No paid API keys are needed. The default model is `qwen2.5-coder:7b`.

## Run

Python 3.10+ is required:

```sh
python3 -m pip install -e .
python3 -m mypa --help
python3 -m mypa web --port 3210
```

On Windows use `python` instead of `python3`. The compatibility command `python -m mypa --web` also works. Open http://127.0.0.1:3210 and choose Settings. The server binds to loopback only.

```sh
mypa chat "Explain this project"
mypa chat
mypa config --show
mypa config --set-default local/qwen2.5-coder:7b
mypa rules --list
mypa rules --add shell "rm *" deny
mypa rules --remove 0
```

Interactive chat keeps conversation history until `/exit`. Errors leave the conversation history intact so you can retry.

## Providers and settings

Install Ollama, start its service, and download the model if it is not already installed:

```sh
ollama serve
# In another terminal:
ollama pull qwen2.5-coder:7b
python3 -m mypa agent "Read this project and explain its structure"
```

To work on another project:

```sh
mypa agent --workspace /var/www/html/my-ai-apps/my-pa
```

In interactive mode, `/workspace /path/to/project` switches projects and clears conversation history. A request beginning with an existing absolute directory also selects that project for the request. Commands automatically use that project's `.venv` when present. For Python dependencies, the agent is instructed to inspect existing requirements and use or create a virtual environment. Text-form JSON tool calls emitted by a local model are recovered and executed through the same tool rules.

The web chat defaults to Agent mode; Quick chat is text-only. `mypa agent` also supports interactive conversations; `mypa chat` remains text-only. Agent mode requires a local tool-capable Ollama model. It uses Ollama's native tool-calling loop: https://docs.ollama.com/capabilities/tool-calling. Settings displays installed local models. This workspace includes `mypa.jsonc` to select the installed local model even if older global settings select another provider. Edit that file to change project settings.

Optional cloud and OpenCode adapters remain available for text chat, but the local agent never calls them.

Blank key fields preserve existing keys. Enter `{env:VARIABLE_NAME}` to restore an environment reference. Entered literal keys are saved in the local config, never returned by the settings API or CLI config display; on POSIX, new config files have mode 0600. Environment references keep secrets out of config files.

Configuration layers, with later layers overriding earlier ones:

1. Built-in defaults.
2. `$XDG_CONFIG_HOME/mypa/mypa.jsonc` or `~/.config/mypa/mypa.jsonc`.
3. `mypa.jsonc` in the working directory.

Settings writes update the global file without copying project overrides into it. Project overrides remain authoritative; edit the project file if a saved setting does not take effect. JSONC supports line/block comments and trailing commas. Invalid config produces an error rather than silently resetting settings. `mypa.example.jsonc` is a starting point. These are myPA settings, not an upstream OpenCode config schema.

## Tool rules

Local tools are enabled by default. Set the workspace, disable shell execution, or limit tool rounds in Settings (`agent.workspace`, `agent.shell_enabled`, `agent.max_steps`). File tools reject paths and symlinks outside the workspace and protect `.git`, `.aws`, `.agents`, and `.codex`. Writes are atomic; edits require exactly one matching text block. Dedicated directory, move and delete tools support file management. Nonempty directory deletion requires `recursive: "true"`; moving or deleting the workspace root or trees containing protected directories is rejected. Action requests with no successful tool execution receive two retries and an explicit unverified-completion message if the model still fails to act. Accumulated tool history is bounded while preserving the current request and recent tool results.

**Command execution is trusted local access, not an operating-system sandbox:** commands run with the server user's access, including outside the file-tool workspace. Only use the loopback UI yourself. Set `shell_enabled` to false to disable commands. Rules for `read`, `write`, `shell`, `web`, or individual tool names can restrict actions; later matching rules win. Both `deny` and `ask` block tools. OpenCode has separate upstream rules and blocks unlisted tools.

The activity log shows executed tools, results and errors. Conversations persist in this browser's local storage; New chat clears them. Model requests have a five-minute timeout, commands a 60-second timeout, and runs a configurable round limit. File reads and writes are capped at 256 KB, with tool results truncated for context. Web search requires internet access, and DuckDuckGo may rate-limit or challenge requests; errors are shown instead of fabricated results. The `encyclopedia_search` tool provides a separate keyless Wikipedia search when general search engines are blocked. There is no browser automation or interactive approval flow.

## Guided installers

Windows: double-click `Setup-myPA.bat`. Linux/macOS: run `sh Setup-myPA.sh`. The setup scripts ask before installing packages, downloading local models, and creating launchers. Ollama model downloads are offered only when its executable is installed.

The optional Debian builder is `sh build_deb.sh`; it asks before building and requires `dpkg-deb`. The generated launcher changes to `/opt/mypa`, where the packaged source and web UI are installed.

## Desktop

Python and the `requests` dependency must be installed separately; the desktop package includes backend source and web assets.

```sh
cd desktop
npm install
npm start
npm run dist
```

The app starts its own Python backend on an available loopback port, waits for its health check, and stops it when the app exits. Set `MYPA_PYTHON` to choose a Python executable. Set `MYPA_URL` to attach to an existing myPA server. `dist` builds for the host OS; cross-platform packaging requires the appropriate signing and build tools.

## Validation

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
node --check web/settings.js
node --check desktop/main.js
python3 -m pip wheel --no-deps .
```

The tests exercise JSONC parsing, config layering and updates, credential redaction, rule validation, CLI aliases, provider payloads, OpenCode event parsing, HTTP errors, origin checks, and served assets. Provider calls are mocked; real credentials and provider availability are needed to validate live model responses.

The conversation screen defaults to **Agent** with file, command, and web tools.
Select **Quick chat** for text-only answers.
Both modes use the configured local model (`qwen2.5-coder:7b` by default) and
stream output immediately; Agent mode also shows tool activity during execution.
The model stays loaded for 30 minutes, and recent conversation history is bounded
to reduce prompt processing. Agent requests use an 8192-token context with up to 2048 generated tokens per
model step. Longer tasks still depend on CPU/GPU speed and tool execution time.
Restart the Python backend or desktop application after updating to enable the
streaming endpoint, then refresh the conversation page.
