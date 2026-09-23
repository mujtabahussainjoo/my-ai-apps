"""Windows guided setup for myPA. Every action asks first.

Usage:
  python setup_win.py                  # full guided setup
  python setup_win.py --check-only     # env checks, no prompts, no changes
  python setup_win.py --shortcuts-only # only offer launchers/shortcuts
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ask(q: str, default_no: bool = True) -> bool:
    hint = " [y/N] " if default_no else " [Y/n] "
    ans = input(q + hint).strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")


def check_env() -> bool:
    ok = True
    print(f"Python {sys.version.split()[0]}", end="")
    if sys.version_info < (3, 10):
        print("  -> NEEDS UPGRADE (myPA requires >= 3.10)")
        ok = False
    else:
        print("  -> OK")
    print("pip:", shutil.which("pip") or "not found")
    print("ollama (optional, local models):", shutil.which("ollama") or "not found")
    print("node (optional, desktop only):", shutil.which("node") or "not found")
    return ok


def pip_install() -> None:
    print("\n--- Python package ---")
    if ask("Install myPA Python package (pip install -e .)?"):
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", str(ROOT)])
    else:
        print("Skipped.")


def make_launchers() -> None:
    print("\n--- Launchers / shortcuts ---")
    bat = ROOT / "mypa.bat"
    if ask(f"Create {bat.name} launcher (runs myPA web UI)?"):
        bat.write_text(
            '@echo off\r\ncd /d "%~dp0"\r\npython -m mypa --web\r\npause\r\n',
            encoding="utf-8",
        )
        print(f"Created {bat}")
    else:
        print("Skipped launcher.")
    if ask("Create Start Menu + Desktop shortcuts?"):
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$t = $ws.CreateShortcut(\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\myPA.lnk\"); "
            f"$t.TargetPath = '{bat}'; $t.WorkingDirectory = '{ROOT}'; $t.Save(); "
            f"$d = $ws.CreateShortcut(\"$env:USERPROFILE\\Desktop\\myPA.lnk\"); "
            f"$d.TargetPath = '{bat}'; $d.WorkingDirectory = '{ROOT}'; $d.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps])
        print("Shortcuts created.")
    else:
        print("Skipped shortcuts.")


def main() -> None:
    if "--check-only" in sys.argv:
        ok = check_env()
        sys.exit(0 if ok else 1)
    if "--shortcuts-only" in sys.argv:
        make_launchers()
        return
    print("=== myPA Windows setup ===")
    check_env()
    pip_install()
    print("\n--- Configuration wizard ---")
    if ask("Run the setup wizard (providers, local models, keys)?", default_no=False):
        subprocess.run([sys.executable, str(ROOT / "setup_wizard.py")])
    else:
        print("Skipped (run 'python setup_wizard.py' any time).")
    make_launchers()
    print("\nDone. Double-click mypa.bat or run:  python -m mypa --web")


if __name__ == "__main__":
    main()
