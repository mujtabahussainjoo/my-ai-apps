/**
 * Installs / removes the desktop & app-menu entries for both platforms.
 *
 * Windows: Desktop + Start Menu shortcuts. The shortcut runs `node.exe` on
 * scripts/launch.js — Smart App Control blocks shell-running .vbs/.bat files
 * ("Dangerous file extension from the web"), but node.exe is trusted.
 *
 * Linux: Desktop entry, application-menu entry (~/.local/share/applications)
 * and an icon in the hicolor theme, so it shows up in the app grid.
 *
 * Everything is idempotent and best-effort: a missing shortcut must never stop
 * the app from starting.
 */
const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";
const LOCAL_CWD = process.env.SystemRoot || "C:\\Windows";
const APP_NAME = "Visible AI Assistant";
const ICON_PNG = path.join(ROOT, "assets", "icon.png");
const ICON_ICO = path.join(ROOT, "assets", "icon.ico");
const LAUNCHER = path.join(ROOT, "scripts", "launch.js");
const UNINSTALLER = path.join(ROOT, "scripts", "uninstall.js");
const STAMP = path.join(ROOT, ".install-stamp");

/* ------------------------------------------------------------------ helpers */

function desktopDir() {
  if (IS_WIN) {
    // Desktop is often redirected (OneDrive, group policy), so ask Windows
    // for the real path instead of assuming %USERPROFILE%\Desktop.
    try {
      const res = spawnSync(
        "powershell.exe",
        ["-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
        { encoding: "utf8" }
      );
      const dir = (res.stdout || "").trim();
      if (dir && fs.existsSync(dir)) return dir;
    } catch {
      /* fall back below */
    }
    return path.join(process.env.USERPROFILE || os.homedir(), "Desktop");
  }

  // Honour XDG user dirs (localised Desktop folder names) when available.
  try {
    const res = spawnSync("xdg-user-dir", ["DESKTOP"], { encoding: "utf8" });
    const dir = (res.stdout || "").trim();
    if (res.status === 0 && dir && fs.existsSync(dir)) return dir;
  } catch {
    /* fall back below */
  }
  return path.join(os.homedir(), "Desktop");
}

function psQuote(value) {
  // PowerShell single-quoted literal: avoids the "\\" and '"' escaping traps.
  return "'" + String(value).replace(/'/g, "''") + "'";
}

function runPowerShell(script) {
  try {
    spawnSync("powershell.exe", ["-NoProfile", "-Command", script], { stdio: "ignore" });
  } catch {
    /* shortcuts are a convenience, never fatal */
  }
}

/* ------------------------------------------------------------------ windows */

function windowsNodeExe() {
  const exe = process.execPath;
  if (/node\.exe$/i.test(exe) && fs.existsSync(exe)) return exe;
  try {
    const res = spawnSync("where", ["node.exe"], { encoding: "utf8", cwd: LOCAL_CWD });
    const found = (res.stdout || "")
      .split(/\r?\n/)
      .map((s) => s.trim())
      .find(Boolean);
    return found || null;
  } catch {
    return null;
  }
}

function windowsIconDir() {
  const base = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
  return path.join(base, "Visible AI Assistant");
}

// Explorer will not reliably resolve a shortcut icon that lives on a
// \\wsl.localhost\... share (it silently falls back to node.exe's icon), so
// the .ico is copied to a local folder and referenced from there.
function windowsAppIcon() {
  try {
    const dir = windowsIconDir();
    fs.mkdirSync(dir, { recursive: true });
    const target = path.join(dir, "icon.ico");
    if (!fs.existsSync(ICON_ICO)) return "";
    const srcSize = fs.statSync(ICON_ICO).size;
    if (!fs.existsSync(target) || fs.statSync(target).size !== srcSize) {
      fs.copyFileSync(ICON_ICO, target);
    }
    return target;
  } catch {
    return "";
  }
}

function windowsStartMenuDir() {
  const appData = process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
  return path.join(appData, "Microsoft", "Windows", "Start Menu", "Programs");
}

function windowsEntries() {
  const nodeExe = windowsNodeExe();
  const target = nodeExe || "cmd.exe";
  const appArgs = nodeExe ? `"${LAUNCHER}"` : `/c ""${path.join(ROOT, "Start Assistant.bat")}""`;
  const uninstallArgs = nodeExe ? `"${UNINSTALLER}"` : appArgs;
  const icon = windowsAppIcon();
  const startMenu = windowsStartMenuDir();
  return [
    { path: path.join(desktopDir(), `${APP_NAME}.lnk`), target, args: appArgs, icon, name: APP_NAME },
    { path: path.join(startMenu, `${APP_NAME}.lnk`), target, args: appArgs, icon, name: APP_NAME },
    {
      path: path.join(startMenu, `Uninstall ${APP_NAME}.lnk`),
      target,
      args: uninstallArgs,
      icon,
      name: `Uninstall ${APP_NAME}`,
    },
  ];
}

function installWindows() {
  const entries = windowsEntries();
  const iconSig = fs.existsSync(ICON_ICO)
    ? `${fs.statSync(ICON_ICO).size}:${fs.statSync(ICON_ICO).mtimeMs}`
    : "none";
  const signature = JSON.stringify({ iconSig, entries: entries.map((e) => [e.path, e.target, e.args, e.icon]) });
  const allPresent = entries.every((e) => fs.existsSync(e.path));
  if (allPresent && readStamp() === signature) return;

  const lines = ["$ErrorActionPreference = 'SilentlyContinue';"];
  for (const entry of entries) {
    lines.push(`$s = (New-Object -ComObject WScript.Shell).CreateShortcut(${psQuote(entry.path)});`);
    lines.push(`$s.TargetPath = ${psQuote(entry.target)};`);
    lines.push(`$s.Arguments = ${psQuote(entry.args)};`);
    lines.push(`$s.WorkingDirectory = ${psQuote(LOCAL_CWD)};`);
    if (entry.icon) lines.push(`$s.IconLocation = ${psQuote(entry.icon)};`);
    lines.push(`$s.Description = ${psQuote(entry.name)};`);
    lines.push("$s.WindowStyle = 7;");
    lines.push("$s.Save();");
  }
  runPowerShell(lines.join(" "));
  // Best-effort icon-cache refresh; the shortcut itself is already correct.
  try {
    spawnSync("ie4uinit.exe", ["-show"], { stdio: "ignore" });
  } catch {
    /* ignore */
  }
  writeStamp(signature);
}

function uninstallWindows() {
  for (const entry of windowsEntries()) {
    try {
      fs.unlinkSync(entry.path);
    } catch {
      /* already gone */
    }
  }
  try {
    // Remove only our icon: the folder also holds the portable Node.js copy
    // used when the machine had none (deleting it would break the uninstaller
    // itself while it is running from that copy).
    fs.unlinkSync(path.join(windowsIconDir(), "icon.ico"));
  } catch {
    /* already gone */
  }
  try {
    fs.unlinkSync(STAMP);
  } catch {
    /* ignore */
  }
}

/* -------------------------------------------------------------------- linux */

function linuxDesktopEntry(execPath) {
  return [
    "[Desktop Entry]",
    "Type=Application",
    `Name=${APP_NAME}`,
    "Comment=Visible-on-screenshare desktop AI assistant (BYOK)",
    `Exec="${execPath}"`,
    `Path=${ROOT}`,
    `Icon=${linuxIconPath()}`,
    "Terminal=false",
    "StartupWMClass=AI Assistant",
    "Categories=Utility;Development;",
    "Keywords=ai;assistant;chat;openai;anthropic;",
    "",
  ].join("\n");
}

function linuxIconPath() {
  return path.join(os.homedir(), ".local", "share", "icons", "hicolor", "256x256", "apps", "visible-ai-assistant.png");
}

function linuxEntries() {
  const launcher = path.join(ROOT, "start-assistant.sh");
  const entry = linuxDesktopEntry(launcher);
  return [
    { path: path.join(desktopDir(), `${APP_NAME}.desktop`), content: entry, trust: true },
    {
      path: path.join(os.homedir(), ".local", "share", "applications", "visible-ai-assistant.desktop"),
      content: entry,
      trust: false,
    },
  ];
}

function installLinux() {
  const iconTarget = linuxIconPath();
  const entries = linuxEntries();
  const signature = JSON.stringify({
    icon: fs.existsSync(ICON_PNG) ? fs.statSync(ICON_PNG).size : 0,
    entries: entries.map((e) => [e.path, e.content]),
  });
  const allPresent = entries.every((e) => fs.existsSync(e.path)) && fs.existsSync(iconTarget);
  if (allPresent && readStamp() === signature) return;

  if (fs.existsSync(ICON_PNG)) {
    try {
      fs.mkdirSync(path.dirname(iconTarget), { recursive: true });
      fs.copyFileSync(ICON_PNG, iconTarget);
    } catch {
      /* icon is cosmetic */
    }
  }

  for (const entry of entries) {
    try {
      fs.mkdirSync(path.dirname(entry.path), { recursive: true });
      if (!fs.existsSync(entry.path) || fs.readFileSync(entry.path, "utf8") !== entry.content) {
        fs.writeFileSync(entry.path, entry.content);
      }
      fs.chmodSync(entry.path, 0o755);
      if (entry.trust) {
        // GNOME needs the file marked trusted to be double-clickable.
        spawnSync("gio", ["set", entry.path, "metadata::trusted", "true"], { stdio: "ignore" });
        spawnSync("dbus-launch", ["gio", "set", entry.path, "metadata::trusted", "true"], { stdio: "ignore" });
      }
    } catch {
      /* shortcut is a convenience, never fatal */
    }
  }
  writeStamp(signature);
}

function uninstallLinux() {
  for (const entry of linuxEntries()) {
    try {
      fs.unlinkSync(entry.path);
    } catch {
      /* already gone */
    }
  }
  try {
    fs.unlinkSync(linuxIconPath());
  } catch {
    /* ignore */
  }
  try {
    fs.unlinkSync(STAMP);
  } catch {
    /* ignore */
  }
}

/* --------------------------------------------------------------------- api */

function readStamp() {
  try {
    return fs.readFileSync(STAMP, "utf8").trim();
  } catch {
    return "";
  }
}

function writeStamp(value) {
  try {
    fs.writeFileSync(STAMP, value + "\n");
  } catch {
    /* ignore */
  }
}

function installShortcuts() {
  try {
    if (IS_WIN) installWindows();
    else installLinux();
  } catch {
    /* never block startup */
  }
}

function uninstallShortcuts() {
  try {
    if (IS_WIN) uninstallWindows();
    else uninstallLinux();
  } catch {
    /* ignore */
  }
}

module.exports = { installShortcuts, uninstallShortcuts, APP_NAME, ROOT, IS_WIN };
