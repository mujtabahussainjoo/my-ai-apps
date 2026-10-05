# Completion review

The original source had no separate analysis document. The README was used to define scope: a Python provider wrapper with CLI, web settings, optional desktop, and guided installers.

Fixed gaps:

- The default provider returned a scaffold echo. It now executes installed OpenCode and parses JSON text events, with actionable failures.
- Provider requests ignored the selected model and flattened conversation roles. Selected models and structured history now reach the adapters.
- Settings ignored API-key inputs and replaced nested provider objects. Keys now persist, blank inputs preserve credentials, and recursive updates retain defaults.
- JSONC parsing corrupted comment markers in strings and silently ignored broken files. Parsing preserves strings, accepts inline comments/trailing commas, and reports invalid files.
- Global saves copied project-specific configuration. Global updates now preserve layer boundaries and write atomically.
- The documented `--web` CLI command failed. Both `web` and `--web` now launch the server; CLI errors have readable messages and nonzero exits.
- HTTP handlers crashed on malformed input and returned provider failures as successful chat replies. Request validation and meaningful status codes now distinguish errors.
- Rule data was stored without affecting upstream actions. Rules now configure the dedicated OpenCode agent; tool approval requests are blocked in this noninteractive interface.
- Chat allowed overlapping requests and lacked failure recovery. Send controls now serialize requests, display status/errors, and preserve retry text.
- The desktop stub needed a prestarted server and had no dependencies/build metadata. It now manages a Python backend and includes packaging metadata and resources.
- Wheels omitted the web UI. A build hook includes the canonical web assets in wheels and source archives.
- Ollama setup offered downloads when its executable was missing. Downloads are now offered only with an installed executable.
- The Debian launcher could not import its backend from arbitrary directories, and Depends was incorrectly indented. Both are corrected.

Verification uses adapter mocks and an actual temporary loopback HTTP server. Live cloud responses, Electron GUI execution, Windows/macOS installers, and signed desktop distribution require their respective credentials/platforms; those are not claimed as tested.
