#!/usr/bin/env node
"use strict";

/**
 * One-click launcher (Windows + Linux/WSL).
 *
 * 1. Installs dependencies if node_modules is missing.
 * 2. Rebuilds only when src/ is newer than dist/.
 * 3. Starts the Electron app detached and exits.
 * 4. Installs Desktop + Start Menu / app-grid entries on first run, so it can
 *    be started from an icon afterwards (see scripts/shortcuts.js).
 * 5. `--install` only installs the entries; `--help` prints usage.
 */

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const IS_WIN = process.platform === "win32";
// When the project lives on \\wsl.localhost\... a child process started with
// that UNC path as its working directory dies immediately, and cmd.exe
// refuses UNC cwd for npm. Detect it and fall back to a local directory.
const ROOT_IS_UNC = ROOT.startsWith("\\\\");
const LOCAL_CWD = process.env.SystemRoot || "C:\\Windows";
const IS_WSL = (() => {
  if (!IS_WIN && process.platform === "linux") {
    try {
      return fs.readFileSync("/proc/version", "utf8").toLowerCase().includes("microsoft");
    } catch {
      return false;
    }
  }
  return false;
})();

function log(msg) {
  process.stdout.write(`[assistant] ${msg}\n`);
}

function newestMtime(dir) {
  let newest = 0;
  const walk = (d) => {
    let entries;
    try {
      entries = fs.readdirSync(d, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const p = path.join(d, entry.name);
      if (entry.isDirectory()) {
        walk(p);
      } else {
        try {
          const t = fs.statSync(p).mtimeMs;
          if (t > newest) newest = t;
        } catch {
          /* ignore */
        }
      }
    }
  };
  walk(dir);
  return newest;
}

function electronBinary() {
  const dist = path.join(ROOT, "node_modules", "electron", "dist");
  if (!fs.existsSync(dist)) return null;
  if (IS_WIN || IS_WSL) {
    const exe = path.join(dist, "electron.exe");
    if (fs.existsSync(exe)) return exe;
  }
  const bin = path.join(dist, "electron");
  if (fs.existsSync(bin)) return bin;
  return null;
}

function runNpm(args) {
  if (IS_WIN && ROOT_IS_UNC) {
    // pushd maps a temporary drive so npm works from a UNC share.
    const quoted = `pushd "${ROOT}" && npm ${args.join(" ")} && popd`;
    const res = spawnSync("cmd.exe", ["/d", "/s", "/c", quoted], {
      stdio: "inherit",
      cwd: LOCAL_CWD,
    });
    return res.status === 0;
  }
  const cmd = IS_WIN ? "npm.cmd" : "npm";
  const res = spawnSync(cmd, args, {
    cwd: ROOT,
    stdio: "inherit",
    shell: IS_WIN,
  });
  return res.status === 0;
}

function hasNodeModules() {
  return fs.existsSync(path.join(ROOT, "node_modules", "electron"));
}

function needsBuild() {
  const main = path.join(ROOT, "dist", "main.js");
  if (!fs.existsSync(main)) return true;
  const built = fs.statSync(main).mtimeMs;
  const src = Math.max(
    newestMtime(path.join(ROOT, "src")),
    (() => {
      try {
        return fs.statSync(path.join(ROOT, "scripts", "copy-assets.js")).mtimeMs;
      } catch {
        return 0;
      }
    })()
  );
  return src > built;
}

function showErrorBox(message) {
  if (!IS_WIN) {
    log(`ERROR: ${message}`);
    return;
  }
  const escaped = message.replace(/'/g, "''");
  spawnSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-Command",
      `Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('${escaped}','Visible AI Assistant') | Out-Null`,
    ],
    { stdio: "ignore" }
  );
}

/* ---------------------------------------------------------------- shortcuts */

// Desktop / Start Menu / app-grid entries live in scripts/shortcuts.js so the
// uninstaller can reuse exactly the same paths.
const { installShortcuts } = require("./shortcuts");

function installShortcut() {
  try {
    installShortcuts();
  } catch (err) {
    // A missing Desktop folder or a locked Start Menu must not stop the app.
    log(`Warning: could not create the app entries (${err.message}).`);
  }
}

/* -------------------------------------------------------------------- main */

function usage() {
  process.stdout.write(
    [
      "Usage: node scripts/launch.js [--install] [--help]",
      "",
      "  (no flag)   install dependencies, build, register the app, then start it",
      "  --install   install dependencies, build and register the app, then exit",
      "  --help      show this help",
      "",
      "Normally you never call this directly: Start Assistant.bat /",
      "Start Assistant.vbs / start-assistant.sh run scripts/bootstrap.* which",
      "fetch a portable Node.js first when the system has none.",
      "",
    ].join("\n")
  );
}

/** Install npm packages (incl. Electron) and build, if not already done. */
function ensureRuntime() {
  if (!hasNodeModules()) {
    log("Installing dependencies (first run only, this can take a minute)...");
    if (!runNpm(["install"])) {
      showErrorBox(
        "npm install failed. Check your internet connection and try again.\n\n" +
          "Details are printed in the setup window."
      );
      process.exit(1);
    }
  }

  if (needsBuild()) {
    log("Building...");
    if (!runNpm(["run", "build"])) {
      showErrorBox(
        "Build failed. Run `npm install` then `npm run build` manually to see the error."
      );
      process.exit(1);
    }
  }

  if (!electronBinary()) {
    log("Electron binary missing after install. Running npm install again...");
    if (!runNpm(["install"])) {
      showErrorBox("Could not download Electron. Check your internet connection and retry.");
      process.exit(1);
    }
  }
}

function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--help") || argv.includes("-h")) {
    usage();
    return;
  }
  const installOnly = argv.includes("--install");

  ensureRuntime();

  if (process.env.VISIBLE_AI_SKIP_SHORTCUTS === "1") {
    log("Skipping app entries (VISIBLE_AI_SKIP_SHORTCUTS=1).");
  } else {
    installShortcut();
  }

  if (installOnly) {
    log("App installed. Launch it from the Desktop / Start Menu / app grid icon.");
    return;
  }

  const exe = electronBinary();
  if (!exe) {
    showErrorBox("Electron binary not found after install.");
    process.exit(1);
  }

  const args = [
    path.join(ROOT, "dist", "main.js"),
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--no-sandbox",
  ];

  // Keep the child's output in launch.log so silent-start failures are
  // diagnosable, and detach it so the launcher can exit right away.
  let stdio = "ignore";
  try {
    const logPath = path.join(ROOT, "launch.log");
    const fd = fs.openSync(logPath, "a");
    stdio = ["ignore", fd, fd];
  } catch {
    /* fall back to ignore */
  }

  const child = spawn(exe, args, {
    // Never pass windowsHide here: Node maps it to STARTF_USESHOWWINDOW /
    // SW_HIDE, which makes Windows ignore the app's first ShowWindow call
    // and the window silently stays hidden. electron.exe is a GUI binary,
    // so no console window appears anyway.
    cwd: ROOT_IS_UNC ? LOCAL_CWD : ROOT,
    detached: true,
    stdio,
  });
  child.on("error", (err) => {
    showErrorBox(`Could not start Electron: ${err.message}`);
  });
  child.unref();
  log("Started.");
}

main();
