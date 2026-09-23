"""myPA setup wizard — asks first, never auto-installs."""
from mypa.installer import check_python, check_node, check_ollama, check_opencode, ask
from mypa.config import load, save_global

print("=== myPA setup wizard ===")
check_python()
check_node()
print()
print("--- Optional: Python deps ---")
if ask("Install Python package 'requests' for live LLM calls? (pip install)"):
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "requests"])
else:
    print("Skipped.")
print()
print("--- Optional: local models (Ollama) ---")
print("Best local models: llama3.1:8b, mistral:7b, codellama:7b, phi3:mini")
check_ollama()
print()
print("--- Optional: upstream opencode CLI ---")
check_opencode()
print()
print("--- Default provider ---")
cfg = load()
print("default_model =", cfg["default_model"], "(opencode free, enabled)")
if ask("Keep opencode free model as default?", default_no=False):
    pass
else:
    cfg["default_model"] = input("Enter default (e.g. openai/gpt-4o-mini): ").strip()
    save_global(cfg)
print()
print("Set keys via Web UI /settings.html or env vars:")
print("  OPENAI_API_KEY, ANTHROPIC_API_KEY")
print("Done. Run: python -m mypa --web")
