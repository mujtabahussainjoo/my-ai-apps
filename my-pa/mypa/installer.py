"""Permission-first install checks. Never installs without explicit yes."""
from __future__ import annotations
import shutil
import urllib.request

BEST_LOCAL_MODELS = ["qwen2.5-coder:7b", "mistral:7b", "codellama:7b", "phi3:mini"]


def ask(q: str, default_no=True) -> bool:
    hint = " [y/N] " if default_no else " [Y/n] "
    ans = input(q + hint).strip().lower()
    if not ans:
        return not default_no
    return ans in ("y", "yes")


def check_python() -> None:
    import sys
    print(f"Python {sys.version.split()[0]} detected.")
    if sys.version_info < (3, 10):
        print("WARNING: myPA needs Python >= 3.10. Please upgrade manually.")


def check_node() -> None:
    print("Node:", shutil.which("node") or "not found (Desktop/Electron optional only).")


def check_ollama() -> None:
    executable = shutil.which("ollama")
    if not executable:
        print("Ollama not found. Install it manually from https://ollama.com, then rerun this wizard.")
        return
    print("Ollama found.")
    if ask("Download a local model with ollama pull?"):
        import subprocess
        print("Suggested models:", ", ".join(BEST_LOCAL_MODELS))
        model = input("Model [qwen2.5-coder:7b]: ").strip() or "qwen2.5-coder:7b"
        result = subprocess.run([executable, "pull", model])
        if result.returncode:
            print("Model download failed; check Ollama and retry.")


def check_opencode() -> None:
    if shutil.which("opencode"):
        print("opencode CLI found — myPA can delegate to it.")
    else:
        print("opencode CLI not found (optional). myPA works standalone; install from https://opencode.ai if wanted.")
        if ask("Try installing opencode via its official script now?"):
            print("Run manually per OS — see install.ps1 / install.sh. Not auto-run from here.")
