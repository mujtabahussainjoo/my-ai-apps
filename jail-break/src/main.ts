import { app, BrowserWindow, desktopCapturer, globalShortcut, ipcMain, screen, session, shell } from "electron";
import * as fs from "fs";
import * as path from "path";

// Win32 SetWindowDisplayAffinity affinity values (WinUser.h, user32.dll).
// WDA_NONE = 0x0             -> normal, included in capture (default)
// WDA_MONITOR = 0x1          -> excluded from fullscreen magnification
// WDA_EXCLUDEFROMCAPTURE = 0x11 -> excluded from screen capture / screenshare
const WDA_NONE = 0x0;
const WDA_MONITOR = 0x1;
const WDA_EXCLUDEFROMCAPTURE = 0x11;

// Extended window styles (WinUser.h).
const GWL_EXSTYLE = -20;
const WS_EX_TOOLWINDOW = 0x00000080;
const WS_EX_APPWINDOW = 0x00040000;

function nativeAddress(hwndBuffer: Buffer): number {
  return hwndBuffer.length >= 8
    ? Number(hwndBuffer.readBigUInt64LE(0))
    : hwndBuffer.readUInt32LE(0);
}

function setWindowDisplayAffinityDirect(
  hwndBuffer: Buffer,
  affinity: number
): boolean {
  // Direct user32.dll SetWindowDisplayAffinity(HWND hWnd, DWORD dwAffinity).
  // Tries koffi first, then ffi-napi. Returns true on success.
  // Both are OPTIONAL deps — caller must tolerate false (fallback is
  // BrowserWindow.setContentProtection, which does the same syscall).
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const koffi = require("koffi") as {
      load: (lib: string) => {
        stdcall: (fn: string, ret: string, params: string[]) => (...a: unknown[]) => unknown;
      };
      as: (v: unknown, t: string) => unknown;
    };
    const user32 = koffi.load("user32.dll");
    const SetWindowDisplayAffinity = user32.stdcall(
      "SetWindowDisplayAffinity",
      "bool",
      ["void*", "uint32"]
    );
    // hwndBuffer is the raw HWND bytes from getNativeWindowHandle().
    // koffi accepts a number address or void*; read it little-endian.
    const addr = nativeAddress(hwndBuffer);
    const ok = SetWindowDisplayAffinity(koffi.as(addr, "void*"), affinity);
    if (ok) return true;
  } catch {
    // koffi not installed — fall through to ffi-napi attempt.
  }

  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const ffi = require("ffi-napi") as {
      Library: (lib: string, fns: Record<string, unknown>) => {
        SetWindowDisplayAffinity: (hwnd: Buffer, affinity: number) => boolean;
      };
    };
    const user32 = ffi.Library("user32", {
      SetWindowDisplayAffinity: ["bool", ["pointer", "uint32"]],
    });
    return user32.SetWindowDisplayAffinity(hwndBuffer, affinity) === true;
  } catch {
    return false;
  }
}

// Keeps the window out of the taskbar / Alt+Tab / "task view" window list by
// forcing WS_EX_TOOLWINDOW (and clearing WS_EX_APPWINDOW) on the HWND.
// Electron's skipTaskbar already does this, but re-asserting it here keeps
// the app out of the taskbar dropdown even after a show/restore cycle.
// Optional: only works when koffi is installed.
function setToolWindowStyleDirect(hwndBuffer: Buffer): boolean {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const koffi = require("koffi") as {
      load: (lib: string) => {
        stdcall: (fn: string, ret: string, params: string[]) => (...a: unknown[]) => unknown;
      };
      as: (v: unknown, t: string) => unknown;
    };
    const user32 = koffi.load("user32.dll");
    const GetWindowLongPtr = user32.stdcall(
      "GetWindowLongPtrW",
      "int64",
      ["void*", "int32"]
    );
    const SetWindowLongPtr = user32.stdcall(
      "SetWindowLongPtrW",
      "int64",
      ["void*", "int32", "int64"]
    );
    const h = koffi.as(nativeAddress(hwndBuffer), "void*");
    const current = Number(GetWindowLongPtr(h, GWL_EXSTYLE));
    const next = (current | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW;
    if (next === current) return true;
    return Number(SetWindowLongPtr(h, GWL_EXSTYLE, next)) !== 0;
  } catch {
    return false;
  }
}

function applyCaptureExclusion(w: BrowserWindow): void {
  // 1) Keep the window out of the taskbar dropdown / Alt+Tab / task view on
  //    every platform (Windows: WS_EX_TOOLWINDOW; Linux: utility window).
  try {
    w.setSkipTaskbar(true);
  } catch {
    /* ignore */
  }

  if (process.platform !== "win32") return;

  // 2) Electron-native path. On Windows this IS
  //    SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE).
  w.setContentProtection(true);

  // 3) Explicit SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) call,
  //    same syscall, for parity with raw Win32 code. Silent on success —
  //    setContentProtection(true) above already applied the affinity, and
  //    koffi/ffi-napi are optional so no log spam when absent.
  try {
    const hwnd = w.getNativeWindowHandle();
    if (hwnd && hwnd.length) {
      setWindowDisplayAffinityDirect(hwnd as Buffer, WDA_EXCLUDEFROMCAPTURE);
      setToolWindowStyleDirect(hwnd as Buffer);
    }
  } catch {
    /* affinity already applied via setContentProtection */
  }
  void WDA_NONE;
  void WDA_MONITOR;
}

let win: BrowserWindow | null = null;

// Stay On Mode: above fullscreen apps, auto-hide when the mouse is idle,
// come back (without stealing focus) on mouse movement.
let stayMode = false;
let lastCursor = { x: 0, y: 0 };
let lastMoveAt = Date.now();
const STAY_IDLE_MS = 5000;
const STAY_MOVE_PX = 6;

function setStayMode(on: boolean): void {
  stayMode = on;
  lastMoveAt = Date.now();
  if (win) {
    try {
      lastCursor = screen.getCursorScreenPoint();
    } catch {
      /* ignore */
    }
    // 'screen-saver' level stays above fullscreen apps on Windows.
    win.setAlwaysOnTop(true, on ? "screen-saver" : "normal");
    win.setVisibleOnAllWorkspaces(on, on ? { visibleOnFullScreen: true } : undefined);
    if (on && !win.isVisible()) win.show();
  }
}

function pollStayMode(): void {
  if (!stayMode || !win) return;
  try {
    const p = screen.getCursorScreenPoint();
    if (Math.abs(p.x - lastCursor.x) + Math.abs(p.y - lastCursor.y) > STAY_MOVE_PX) {
      lastCursor = p;
      lastMoveAt = Date.now();
      // Come out on mouse movement, without stealing focus.
      if (!win.isVisible()) win.showInactive();
    } else if (Date.now() - lastMoveAt > STAY_IDLE_MS && win.isVisible()) {
      win.hide();
    }
  } catch {
    /* ignore */
  }
}

function createWindow(): void {
  const iconPath = path.join(__dirname, "..", "assets", "icon.png");
  win = new BrowserWindow({
    width: 420,
    height: 760,
    // Shrinkable down to a phone-sized panel; the renderer reflows at 400px
    // and 340px wide (see the media queries in styles.css).
    minWidth: 320,
    minHeight: 400,
    title: "AI Assistant",
    ...(fs.existsSync(iconPath) ? { icon: iconPath } : {}),
    alwaysOnTop: true,
    show: false,
    // No taskbar button / thumbnail owner: Explorer draws the taskbar, so
    // WDA_EXCLUDEFROMCAPTURE on our HWND can't black out the taskbar icon.
    // Removing the button is the only way it can't appear in capture.
    // Restore via Ctrl+Shift+A hotkey (no taskbar to click).
    skipTaskbar: true,
    autoHideMenuBar: true,
    backgroundColor: "#121216",
    // Frameless: the renderer draws its own titlebar (drag region + min/hide).
    // NOTE: do NOT add titleBarOverlay here — with titleBarStyle:"hidden" it
    // suppresses Electron's "ready-to-show" event (window never shows) and
    // stacks native caption buttons on top of the renderer's own buttons.
    titleBarStyle: "hidden",
    roundedCorners: true,
    hasShadow: true,
    // Hidden from screenshare via SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE).
    // Applied in applyCaptureExclusion() below (setContentProtection + direct user32).
    // NOTE: setContentProtection(true) on Windows =
    //   SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE).
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setMenuBarVisibility(false);

  win.loadFile(path.join(__dirname, "renderer/index.html"));

  // Apply WDA_EXCLUDEFROMCAPTURE once ready + re-apply on show
  // (affinity lives on the HWND, re-assert after visibility changes).
  // NOTE: "ready-to-show" can be suppressed on some Windows setups, so fall
  // back to "did-finish-load" to guarantee the window is actually shown.
  let shown = false;
  const showWindow = (): void => {
    if (shown || !win) return;
    shown = true;
    win.setSkipTaskbar(true);
    applyCaptureExclusion(win);
    win.show();
  };
  win.once("ready-to-show", showWindow);
  win.webContents.once("did-finish-load", showWindow);
  win.on("show", () => {
    if (!win) return;
    // show() can re-add the taskbar button; force it off again.
    win.setSkipTaskbar(true);
    applyCaptureExclusion(win);
  });
  // Restoring re-creates the caption state, so re-assert the taskbar skip
  // and the capture exclusion.
  win.on("restore", () => {
    if (!win) return;
    win.setSkipTaskbar(true);
    applyCaptureExclusion(win);
  });

  win.on("closed", () => {
    win = null;
  });
}

function toggleVisibility(): void {
  if (!win) return;
  if (win.isVisible()) {
    win.hide();
  } else {
    win.show();
    win.focus();
  }
}

// Single instance: a second launch (e.g. double-clicking the launcher
// twice) focuses the existing window instead of starting a second copy.
// Without this, two instances fight over the same user-data-dir cache.
const hasInstanceLock = app.requestSingleInstanceLock();
if (!hasInstanceLock) {
  app.quit();
}

app.whenReady().then(() => {
  if (!hasInstanceLock) return;
  // Allow mic for 🎤 Listen (getUserMedia) + system audio for 📞 caller voice
  // (getDisplayMedia with "Share system audio"). Screenshots still go
  // through the picker; camera stays denied.
  session.defaultSession.setPermissionRequestHandler(
    (webContents, permission, callback) => {
      const p = permission as string;
      if (p === "media" || p === "audioCapture" || p === "display-capture") callback(true);
      else callback(false);
    }
  );
  // Electron has no built-in screen picker: without this handler every
  // getDisplayMedia() rejects (seen as "cancelled"). Auto-grant the primary
  // screen with system-audio loopback so one tap enables caller voice.
  session.defaultSession.setDisplayMediaRequestHandler(
    (_request, callback) => {
      desktopCapturer
        .getSources({ types: ["screen"] })
        .then((sources) => {
          const primary = sources[0];
          if (!primary) {
            callback({});
            return;
          }
          callback({ video: primary, audio: "loopback" });
        })
        .catch(() => callback({}));
    }
  );
  createWindow();

  // A second launch (double-clicked launcher) surfaces the running window
  // instead of spawning a duplicate.
  app.on("second-instance", () => {
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  });

  // Mouse-movement watcher for Stay On Mode (cheap 4Hz cursor poll).
  setInterval(pollStayMode, 250);

  // Global hotkeys (visible, user-initiated)
  globalShortcut.register("CommandOrControl+Shift+A", toggleVisibility);
  globalShortcut.register("CommandOrControl+Shift+H", () => {
    win?.minimize();
  });

  ipcMain.on("toggle-visibility", toggleVisibility);
  ipcMain.on("stay-mode-set", (_e, on: boolean) => setStayMode(on === true));
  ipcMain.on("window-minimize", () => win?.minimize());
  // No taskbar button, so "close" hides to hotkey instead of quitting.
  ipcMain.on("window-hide", () => win?.hide());
  ipcMain.on("open-external", (_e, url: string) => {
    if (url.startsWith("https://")) void shell.openExternal(url);
  });
  // Screen Reader Mode picker data: renderer shows thumbnails, user picks a
  // window each time. No silent background capture — one user pick per read.
  ipcMain.handle("list-screen-sources", async () => {
    const sources = await desktopCapturer.getSources({
      types: ["window", "screen"],
      thumbnailSize: { width: 320, height: 180 },
    });
    return sources.map((s) => ({
      id: s.id,
      name: s.name,
      thumbnail: s.thumbnail.isEmpty() ? "" : s.thumbnail.toDataURL(),
    }));
  });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
