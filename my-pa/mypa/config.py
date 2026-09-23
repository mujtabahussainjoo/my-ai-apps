"""Config load/merge for myPA. Stdlib only."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path

APP = "mypa"
DEFAULT_MODEL = "opencode/muse-spark-1.3-contributor-free"

DEFAULTS = {
    "$schema": "https://opencode.ai/config.json",
    "app": "myPA",
    "theme": "mypa-dark",
    "default_model": DEFAULT_MODEL,
    "models_enabled": [DEFAULT_MODEL],
    # No rules by default. Empty = no allow, no deny, no prohibition.
    # User adds their own via `mypa rules` CLI or Web Settings.
    "permissions": [],
    "providers": {
        "opencode": {"enabled": True, "note": "default, free tier"},
        "openai": {"enabled": False, "api_key": "{env:OPENAI_API_KEY}", "model": "gpt-4o-mini"},
        "anthropic": {"enabled": False, "api_key": "{env:ANTHROPIC_API_KEY}", "model": "claude-sonnet-4-5"},
        "local": {"enabled": False, "base_url": "http://127.0.0.1:11434", "model": "llama3.1:8b"},
    },
}


def _strip_jsonc(text: str) -> str:
    # Strip /* */ blocks, then full-line // comments only.
    # (Inline // stripping would corrupt "https://..." strings.)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]
    return "\n".join(lines)


def _load_file(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(_strip_jsonc(p.read_text(encoding="utf-8")))
    except Exception:
        return {}


def paths() -> tuple[Path, Path]:
    home = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return (home / APP / "mypa.jsonc", Path.cwd() / "mypa.jsonc")


def load() -> dict:
    cfg: dict = json.loads(json.dumps(DEFAULTS))
    for p in paths():
        overlay = _load_file(p)
        for k, v in overlay.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


def save_global(cfg: dict) -> Path:
    g, _ = paths()
    g.parent.mkdir(parents=True, exist_ok=True)
    g.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return g
