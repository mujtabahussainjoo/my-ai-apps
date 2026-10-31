# One-click install / uninstall for NexaPilot AI (desktop)

Put the entire `install/` folder next to your built installer for the easiest experience, or run from a source checkout.

## Ubuntu / Debian Linux

**Option 1: Install a pre-built `.deb` (fastest)**
1. The built package is already at `dist/NexaPilot AI_0.1.0_amd64.deb` (or download a release).
2. Copy it into `install/linux/` if you want `install.sh` to find it automatically, or install it directly with your file manager.
3. Open a terminal in `install/linux/` and run:

```bash
chmod +x install.sh uninstall.sh
./install.sh
```

**Option 2: Build from source + install (one command)**
```bash
./install.sh --build
```
If you don't have build tools yet: `./install.sh --build --system-deps` (installs Rust, Node, uv, WebKitGTK dev packages).

**Launch:** Search for "NexaPilot AI" in your Applications menu, or run `nexapilot-desktop`.

**Uninstall:**
```bash
./uninstall.sh           # keep your chats, approvals, settings
./uninstall.sh --purge   # remove app + local data + vault entries
```
Data is stored in `~/.local/share/nexapilot/`. Secrets are cleared from your OS keyring if `secret-tool` is available.

## Windows 10 / 11 (x64)

1. Download `NexaPilot AI_*_x64-setup.exe` (NSIS) or `*.msi` from the release.
2. Put it in `install/windows/`, or pass its path: `.\install.ps1 -InstallerPath "C:\Users\you\Downloads\NexaPilot AI_0.1.0_x64-setup.exe"`.
3. Right-click `install.ps1` → **Run with PowerShell** (or open PowerShell and run `.\install.ps1`).
   - If PowerShell blocks scripts: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (one time).
   - Unsigned builds trigger SmartScreen: **More info → Run anyway** (or unblock the file in Properties).
4. The installer prints numbered, timestamped steps and writes a full log to `%TEMP%\nexapilot-install-*.log`. A build from source takes 10-20 minutes; the log shows the current step if it appears stuck.
5. Add `-Silent` to run the NSIS installer without its wizard: `.\install.ps1 -Silent`.
6. The installer runs per-user (no admin required for NSIS by default). Launch from the **Start Menu** → **NexaPilot AI**.

**Build from source:** `.\install.ps1 -Build -InstallDeps` (uses `winget` for Rust, Node.js, Git, uv, and the Visual Studio C++ Build Tools; the last is ~5 GB and may show a UAC prompt). Running from `\\wsl.localhost\...` or a network share works: the installer copies the source to `%LOCALAPPDATA%\NexaPilot\build` before building.

**Uninstall (easy):** double-click `Uninstall NexaPilot AI.cmd` and choose whether to keep your chats/settings. Command line:
```powershell
.\uninstall.ps1           # asks what to keep
.\uninstall.ps1 -KeepData # keep data in %APPDATA%\nexapilot
.\uninstall.ps1 -Purge    # remove app + data
```
Revoke Google OAuth grants at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

### If Windows blocks the installer

- **SmartScreen** ("Windows protected your PC"): choose **More info → Run anyway**. `install.ps1` calls `Unblock-File` before launching, which removes the downloaded-file marker.
- **Smart App Control** (Windows 11): there is no per-app allow. It only runs apps signed by a certificate issued by a provider in Microsoft's Trusted Root Program, or unsigned apps its cloud service predicts are safe. Self-signed certificates do not satisfy it. Either sign with a CA-issued code-signing certificate, or turn Smart App Control off in **Windows Security → App & browser control → Smart App Control** (turning it off cannot be undone without reinstalling or resetting Windows).

**Sign a build** — Tauri signs the app binary and the NSIS installer:

```powershell
# certificate already imported into Cert:\CurrentUser\My
.\install.ps1 -Build -InstallDeps -CertificateThumbprint "A1B1A2B2...A9B9A0B0"

# or import a .pfx (prompts for its password)
.\install.ps1 -Build -InstallDeps -PfxPath "C:\certs\codesign.pfx"
```

A new certificate has no SmartScreen reputation yet; warnings disappear as the same certificate signs more releases. Smart App Control accepts valid CA-signed apps.

## macOS (Intel/Apple Silicon)

1. Download `NexaPilot AI_*.dmg` (or `.app`).
2. Put it in `install/macos/`.
3. Open Terminal in `install/macos/` and run:

```bash
chmod +x install.sh uninstall.sh
./install.sh
```

**Build from source:** `./install.sh --build`.
**Uninstall:**
```bash
./uninstall.sh         # keep data
./uninstall.sh --purge # remove app + data
```
Data in `~/Library/Application Support/nexapilot/`.

## One-click files (double-click, no terminal)

| OS | File | What it does |
| --- | --- | --- |
| Linux | `install/linux/Install NexaPilot AI.desktop` | Builds/installs the app, shows progress in a terminal window |
| Linux | `dist/NexaPilot AI_0.1.0_amd64.deb` | Double-click in Files → Ubuntu Software → Install (already built) |
| Linux | `install/linux/Uninstall NexaPilot AI.desktop` | Double-click to uninstall; asks whether to keep data |
| Windows | `install/windows/Install NexaPilot AI.cmd` | Double-click to build/install (PowerShell runs elevated prompts only if needed) |
| Windows | `install/windows/Uninstall NexaPilot AI.cmd` | Double-click to uninstall; asks whether to keep data |
| Windows | `NexaPilot AI_*_x64-setup.exe` | The branded NSIS installer (one click, per-user) |
| macOS | `install/macos/Install NexaPilot AI.command` | Double-click in Finder to build/install |
| macOS | `install/macos/Uninstall NexaPilot AI.command` | Double-click in Finder to uninstall; asks whether to keep data |

The app/installer icon is generated from `desktop/src-tauri/icons/icon-source.png`
(a navy compass + paper-plane mark) and is embedded in the `.deb`, NSIS `.exe`,
`.dmg`, Start Menu shortcut, and the installed app window.

## Notes

- NexaPilot runs **only on loopback** (`127.0.0.1:8765`), uses approvals for side-effecting actions, and stores secrets in your OS credential vault when available.
- Upgrading replaces the app; local data/migrations run automatically.
- The Tauri shell auto-starts the bundled backend sidecar and stops it when the app exits.
- If you already have a backend running on port 8765, the desktop shell will reuse it (dev-friendly).
