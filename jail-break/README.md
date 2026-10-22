# Visible AI Assistant (Electron + TypeScript + BYOK)

Always **visible on screenshare**. No stealth / capture-evasion. Keys stored in localStorage only.

## Install as an app (one click, nothing pre-installed)

Nothing needs to be installed first. The setup scripts fetch everything
themselves on the first click: Node.js (if the system has none), npm packages,
Electron, then build the app and add the icons. Internet is the only
requirement, and **no administrator rights / no `sudo` are needed** (a portable
Node.js copy is used instead of a system package).

**Windows 10/11**
- Double-click **`Install Visible AI Assistant.bat`** to set up only, or
  **`Start Assistant.bat`** to set up *and* start (console shows progress).
- `Start Assistant.vbs` does the same with no console window.
- Setup adds:
  - **Visible AI Assistant** on your Desktop
  - **Visible AI Assistant** in the Start Menu
  - **Uninstall Visible AI Assistant** in the Start Menu
- From then on: double-click the Desktop or Start Menu icon. Done.
- If Windows says *"An Application Control policy has blocked this file"*
  (Smart App Control), run this once instead — it does the same thing:
  ```bat
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" --install
  ```
  The installed shortcuts are not affected: they start the downloaded
  `node.exe` directly, which Smart App Control allows.

**Ubuntu / Debian / Fedora / Arch**
- Double-click **`install-visible-ai-assistant.sh`** (choose *Run*) to set up,
  or **`start-assistant.sh`** to set up *and* start.
- Setup adds the app to your **application grid** and **Desktop**, with its own
  icon, then you can just open it from there.
- If your file manager won't run the script: right-click → *Properties* →
  *Allow executing file as program* (or run `sh start-assistant.sh`).

**Optional terminal form** (same behaviour):
```sh
npm run install-app     # (re)install Desktop / Start Menu / app-grid entries
npm run uninstall-app   # remove the entries (keeps the project + saved keys)
npm run launch          # start
```

Re-running any launcher is safe: dependencies are installed only when missing,
the rebuild happens only when `src/` changed, and a second launch focuses the
already-running window instead of starting a duplicate.

## Where the automatic dependencies live
| | Windows | Linux |
| --- | --- | --- |
| Portable Node.js (only if needed) | `%LOCALAPPDATA%\Visible AI Assistant\node` | `~/.local/share/visible-ai-assistant/node` |
| npm packages + Electron | `node_modules/` in the project | `node_modules/` in the project |
| App icon | `%LOCALAPPDATA%\Visible AI Assistant\icon.ico` | `~/.local/share/icons/hicolor/256x256/apps/` |

Uninstalling removes the shortcuts and the icon. The portable Node.js copy and
`node_modules/` stay behind so reinstalling is instant — delete those folders
(see the table) to reclaim the space. No system-wide changes are made.

## Use
- Provider: OpenAI or Anthropic
- Model defaults: `gpt-4o-mini` / `claude-3-5-sonnet-latest`
- Paste API key -> Save (per-provider, local only)
- Enter = send, 📷 = permission-prompted screenshot attach (visible to OS/share)
- Hotkeys: `Ctrl+Shift+A` show/hide, `Ctrl+Shift+H` minimize
- Settings panel collapses with **Hide/Show**; it starts collapsed on short
  windows so the chat keeps room.

## Answer format
Answers are requested in a fixed, skimmable structure:
- One-line direct answer with the key fact in **bold**
- Pointwise bullets under short `##` headings
- A dedicated **`## Code`** section: fenced, language-tagged blocks with a
  header and a **Copy** button, instead of code mixed into prose
- Compact tables for comparisons, inline `code` for paths/commands/values
- `## Key points` (max 3 bullets) on complex answers

## Notes
- Direct browser-to-API calls, no backend server.
- Anthropic uses `anthropic-dangerous-direct-browser-access: true` header (BYOK desktop pattern).
- Screenshots use `getDisplayMedia` so the OS/share sees the picker.
- **Capture / taskbar hiding:** the window is excluded from screen capture via
  `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, and removed from the
  taskbar, Alt-Tab and the taskbar thumbnail dropdown (`skipTaskbar` +
  `WS_EX_TOOLWINDOW`). There is no taskbar icon by design — use
  `Ctrl+Shift+A` to show/hide.
- On native Linux there is no OS-level "exclude from capture" API; the window
  is still hidden from the taskbar/Alt-Tab. For full capture exclusion run the
  Windows build (this is what WSL interop uses automatically).
- **Responsive:** the window can shrink to 320×400. The layout reflows at
  400px/340px width and 620px/480px height (footer wraps, labels truncate,
  settings fold, code blocks scroll inside their own box).
- The chat input keeps the normal arrow cursor (no I-beam) by design.
