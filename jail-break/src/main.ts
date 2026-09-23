import { app, BrowserWindow, desktopCapturer, globalShortcut, ipcMain, screen, session, shell } from "electron";
import * as path from "path";

// Win32 SetWindowDisplayAffinity affinity values (WinUser.h, user32.dll).
// WDA_NONE = 0x0             -> normal, included in capture (default)
// WDA_MONITOR = 0x1          -> excluded from fullscreen magnification
// WDA_EXCLUDEFROMCAPTURE = 0x11 -> excluded from screen capture / screenshare
const WDA_NONE = 0x0;
const WDA_MONITOR = 0x1;
const WDA_EXCLUDEFROMCAPTURE = 0x11;

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
    const addr =
      hwndBuffer.length >= 8
        ? Number(hwndBuffer.readBigUInt64LE(0))
        : hwndBuffer.readUInt32LE(0);
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

function applyCaptureExclusion(w: BrowserWindow): void {
  if (process.platform !== "win32") return;

  // 1) Electron-native path. On Windows this IS
  //    SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE).
  w.setContentProtection(true);

  // 2) Explicit SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) call,
  //    same syscall, for parity with raw Win32 code. Silent on success —
  //    setContentProtection(true) above already applied the affinity, and
  //    koffi/ffi-napi are optional so no log spam when absent.
  try {
    const hwnd = w.getNativeWindowHandle();
    if (hwnd && hwnd.length) {
      setWindowDisplayAffinityDirect(hwnd as Buffer, WDA_EXCLUDEFROMCAPTURE);
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
  win = new BrowserWindow({
    width: 420,
    height: 760,
    title: "AI Assistant",
    alwaysOnTop: true,
    show: false,
    // No taskbar button / thumbnail owner: Explorer draws the taskbar, so
    // WDA_EXCLUDEFROMCAPTURE on our HWND can't black out the taskbar icon.
    // Removing the button is the only way it can't appear in capture.
    // Restore via Ctrl+Shift+A hotkey (no taskbar to click).
    skipTaskbar: true,
    autoHideMenuBar: true,
    backgroundColor: "#121216",
    titleBarStyle: "hidden",
    titleBarOverlay: { color: "#121216", symbolColor: "#e8e8ea", height: 38 },
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
  win.once("ready-to-show", () => {
    if (!win) return;
    win.setSkipTaskbar(true);
    applyCaptureExclusion(win);
    win.show();
  });
  win.on("show", () => {
    if (!win) return;
    // show() can re-add the taskbar button; force it off again.
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

app.whenReady().then(() => {
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
