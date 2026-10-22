#!/usr/bin/env node
"use strict";

/**
 * Removes the Desktop / Start Menu / app-grid entries installed by
 * scripts/shortcuts.js. The project folder and your saved settings are kept.
 */
const { spawnSync } = require("child_process");
const { uninstallShortcuts, APP_NAME, IS_WIN } = require("./shortcuts");

const quiet = process.argv.includes("--quiet") || process.argv.includes("-q");

uninstallShortcuts();

const message = `Removed the ${APP_NAME} shortcuts.\n\nThe project folder was not deleted. Local API keys stay in the app's browser storage.`;

if (quiet) {
  process.stdout.write(message + "\n");
} else if (IS_WIN) {
  const escaped = message.replace(/'/g, "''").replace(/\r?\n/g, " ");
  try {
    spawnSync(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        "Add-Type -AssemblyName PresentationFramework; " +
          `[System.Windows.MessageBox]::Show('${escaped}','${APP_NAME}') | Out-Null`,
      ],
      { stdio: "ignore" }
    );
  } catch {
    /* no UI available */
  }
} else {
  process.stdout.write(message + "\n");
}
