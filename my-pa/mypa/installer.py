"""Permission-first install checks. Never installs without explicit yes."""
from __future__ import annotations
import shutil
import urllib.request

BEST_LOCAL_MODELS = ["llama3.1:8b", "mistral:7b", "codellama:7b", "phi3:mini"]


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
    if shutil.which("ollama"):
        print("Ollama found.")
        return
    print("Ollama NOT found. Local models need it: https://ollama.ai")
    if ask("Open Ollama download page info (no install)?"):
        print("-> https://ollama.ai  (install manually, then: ollama pull llama3.1:8b)")
    if ask("Pull a local model now with 'ollama pull'? (requires ollama installed)"):
        import subprocess
        print("Best local models:", ", ".join(BEST_LOCAL_MODELS))
        m = input("Which model? [llama3.1:8b]: ").strip() or "llama3.1:8b"
        subprocess.run(["ollama", "pull", m])


def check_opencode() -> None:
    if shutil.which("opencode"):
        print("opencode CLI found — myPA can delegate to it.")
    else:
        print("opencode CLI not found (optional). myPA works standalone; install from https://opencode.ai if wanted.")
        if ask("Try installing opencode via its official script now?"):
            print("Run manually per OS — see install.ps1 / install.sh. Not auto-run from here.")
