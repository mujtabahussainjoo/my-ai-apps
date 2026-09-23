"""Provider calls. OpenAI/Anthropic/Ollama + opencode placeholder."""
from __future__ import annotations
import os
import re

try:
    import requests
except ImportError:  # allow --help / --web without deps
    requests = None  # type: ignore


def _resolve(v: str | None) -> str | None:
    if not v:
        return v
    m = re.fullmatch(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}", v.strip())
    if m:
        return os.environ.get(m.group(1))
    return v


def chat(cfg: dict, messages: list[dict]) -> str:
    provider, _, model = (cfg.get("default_model") or "/").partition("/")
    providers = cfg.get("providers", {})
    if provider == "openai" and providers.get("openai", {}).get("enabled"):
        return _openai(cfg, messages)
    if provider == "anthropic" and providers.get("anthropic", {}).get("enabled"):
        return _anthropic(cfg, messages)
    if provider == "local" and providers.get("local", {}).get("enabled"):
        return _ollama(cfg, messages)
    # default: opencode free / echo fallback (no key needed for scaffold)
    prompt = messages[-1]["content"] if messages else ""
    return (
        f"[myPA:{cfg.get('default_model')}] scaffold reply.\n"
        f"You said: {prompt}\n"
        f"Configure OpenAI/Anthropic/local keys in Settings to get live answers."
    )


def _need_requests():
    if requests is None:
        raise RuntimeError("pip install requests  (or: pip install -e .)")


def _openai(cfg: dict, messages: list[dict]) -> str:
    _need_requests()
    p = cfg["providers"]["openai"]
    key = _resolve(p.get("api_key"))
    if not key:
        return "OpenAI enabled but OPENAI_API_KEY is missing."
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": p.get("model", "gpt-4o-mini"), "messages": messages},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _anthropic(cfg: dict, messages: list[dict]) -> str:
    _need_requests()
    p = cfg["providers"]["anthropic"]
    key = _resolve(p.get("api_key"))
    if not key:
        return "Anthropic enabled but ANTHROPIC_API_KEY is missing."
    text = "\n".join(m["content"] for m in messages)
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={"model": p.get("model", "claude-sonnet-4-5"), "max_tokens": 1024,
              "messages": [{"role": "user", "content": text}]},
        timeout=60,
    )
    r.raise_for_status()
    blocks = r.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks) or str(r.json())


def _ollama(cfg: dict, messages: list[dict]) -> str:
    _need_requests()
    p = cfg["providers"]["local"]
    base = p.get("base_url", "http://127.0.0.1:11434").rstrip("/")
    prompt = "\n".join(m["content"] for m in messages)
    r = requests.post(f"{base}/api/generate",
                      json={"model": p.get("model", "llama3.1:8b"),
                            "prompt": prompt, "stream": False}, timeout=120)
    r.raise_for_status()
    return r.json().get("response", "")
