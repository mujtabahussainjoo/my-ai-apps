# Visible AI Assistant (Electron + TypeScript + BYOK)

Always **visible on screenshare**. No stealth / capture-evasion. Keys stored in localStorage only.

## Setup (Windows)

1. Install Node.js LTS 20+ and restart your terminal:
   `winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements`
2. In this folder:
   ```powershell
   npm install
   npm run build && npm start
   ```

## Use
- Provider: OpenAI or Anthropic
- Model defaults: `gpt-4o-mini` / `claude-3-5-sonnet-latest`
- Paste API key -> Save (per-provider, local only)
- Enter = send, 📷 = permission-prompted screenshot attach (visible to OS/share)
- Hotkeys: `Ctrl+Shift+A` show/hide, `Ctrl+Shift+H` minimize

## Notes
- Direct browser-to-API calls, no backend server.
- Anthropic uses `anthropic-dangerous-direct-browser-access: true` header (BYOK desktop pattern).
- Screenshots use `getDisplayMedia` so the OS/share sees the picker.
- `src/main.ts` intentionally does NOT use `SetWindowDisplayAffinity(EXCLUDEFROMCAPTURE)`.
