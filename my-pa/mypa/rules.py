"""Custom allow/deny rules. Empty by default — user owns them."""
from __future__ import annotations
from .config import load, save_global

EFFECTS = ("allow", "deny", "ask")


def list_rules() -> list:
    return load().get("permissions", [])


def add_rule(action: str, resource: str, effect: str) -> list:
    effect = effect.lower()
    if effect not in EFFECTS:
        raise ValueError(f"effect must be one of {EFFECTS}")
    cfg = load()
    rules = cfg.get("permissions", []) or []
    rules.append({"action": action, "resource": resource, "effect": effect})
    cfg["permissions"] = rules
    save_global(cfg)
    return rules


def remove_rule(index: int) -> list:
    cfg = load()
    rules = cfg.get("permissions", []) or []
    del rules[index]
    cfg["permissions"] = rules
    save_global(cfg)
    return rules


def clear_rules() -> list:
    cfg = load()
    cfg["permissions"] = []
    save_global(cfg)
    return []
