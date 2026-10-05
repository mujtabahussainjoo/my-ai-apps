"""Custom allow/deny rules. Empty by default — user owns them."""
from __future__ import annotations
from .config import load, update_global

EFFECTS = ("allow", "deny", "ask")


def list_rules() -> list:
    return load().get("permissions", [])


def add_rule(action: str, resource: str, effect: str) -> list:
    if not isinstance(effect, str):
        raise ValueError("effect must be text")
    effect = effect.lower()
    if effect not in EFFECTS:
        raise ValueError(f"effect must be one of {EFFECTS}")
    cfg = load()
    rules = cfg.get("permissions", []) or []
    rules.append({"action": action, "resource": resource, "effect": effect})
    cfg["permissions"] = rules
    update_global({"permissions": cfg["permissions"]})
    return rules


def remove_rule(index: int) -> list:
    cfg = load()
    rules = cfg.get("permissions", []) or []
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(rules):
        raise ValueError("Rule index is out of range")
    del rules[index]
    cfg["permissions"] = rules
    update_global({"permissions": cfg["permissions"]})
    return rules


def clear_rules() -> list:
    cfg = load()
    cfg["permissions"] = []
    update_global({"permissions": cfg["permissions"]})
    return []
