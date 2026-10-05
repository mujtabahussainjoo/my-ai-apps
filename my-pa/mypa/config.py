"""Validated JSONC configuration with recursive overlays and atomic writes."""
from __future__ import annotations
import copy
import json
import os
import re
import tempfile
from pathlib import Path

APP = 'mypa'
DEFAULT_MODEL = 'local/qwen2.5-coder:7b'
DEFAULTS = {
    'app': 'myPA', 'theme': 'mypa-dark', 'default_model': DEFAULT_MODEL,
    'models_enabled': [DEFAULT_MODEL], 'permissions': [],
    'agent': {'workspace': '.', 'shell_enabled': True, 'max_steps': 16,
              'num_ctx': 4096, 'num_predict': 1024},
    'providers': {
        'local': {'enabled': True, 'base_url': 'http://127.0.0.1:11434', 'model': 'qwen2.5-coder:7b'},
    },
}


def _strip_jsonc(text: str) -> str:
    # Match strings first so comment markers inside strings survive.
    token = r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/'
    text = re.sub(token, lambda m: m[0] if m[0].startswith('"') else ' ', text)
    token = r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])'
    return re.sub(token, lambda m: m[0] if m[0].startswith('"') else '', text)


def merge(base: dict, overlay: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else copy.deepcopy(value)
    return result


def validate(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise ValueError('Configuration must be an object')
    model = cfg.get('default_model', '')
    if not isinstance(model, str) or '/' not in model or not all(model.split('/', 1)):
        raise ValueError('default_model must be provider/model')
    providers = cfg.get('providers')
    if not isinstance(providers, dict):
        raise ValueError('providers must be an object')
    if model.split('/', 1)[0] not in providers:
        raise ValueError('Unknown default provider')
    for name, provider in providers.items():
        if not isinstance(provider, dict) or not isinstance(provider.get('enabled', False), bool):
            raise ValueError(f'Invalid provider: {name}')
        for key in ('api_key', 'model', 'base_url'):
            if key in provider and not isinstance(provider[key], str):
                raise ValueError(f'{name}.{key} must be text')
        if 'base_url' in provider:
            from urllib.parse import urlparse
            url = urlparse(provider['base_url'])
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
                raise ValueError('base_url must be an HTTP(S) URL without credentials')
    if cfg.get('theme') not in ('mypa-dark', 'mypa-light'):
        raise ValueError('Unknown theme')
    agent = cfg.get('agent', {})
    if not isinstance(agent, dict) or not isinstance(agent.get('workspace', '.'), str) or not isinstance(agent.get('shell_enabled', True), bool):
        raise ValueError('Invalid agent workspace or shell setting')
    steps = agent.get('max_steps', 16)
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= 32:
        raise ValueError('agent.max_steps must be 1–32')
    for field, minimum, maximum in [('num_ctx', 2048, 32768), ('num_predict', 128, 4096)]:
        value = agent.get(field, DEFAULTS['agent'][field])
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f'agent.{field} must be {minimum}–{maximum}')
    if agent.get('num_predict', 1024) >= agent.get('num_ctx', 4096):
        raise ValueError('agent.num_predict must be smaller than agent.num_ctx')
    rules = cfg.get('permissions', [])
    if not isinstance(rules, list):
        raise ValueError('permissions must be a list')
    for rule in rules:
        if not isinstance(rule, dict) or rule.get('effect') not in ('allow', 'deny', 'ask') or any(not isinstance(rule.get(k), str) or not rule[k].strip() for k in ('action', 'resource')):
            raise ValueError('Rules require action, resource, and allow/deny/ask effect')
    return cfg


def _load_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(_strip_jsonc(path.read_text(encoding='utf-8')))
        if not isinstance(value, dict):
            raise ValueError('Expected object')
        return value
    except (ValueError, OSError) as exc:
        raise ValueError(f'Invalid configuration in {path}: {exc}') from exc


def paths() -> tuple[Path, Path]:
    home = Path(os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config'))
    return home / APP / 'mypa.jsonc', Path.cwd() / 'mypa.jsonc'


def load() -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    for path in paths():
        cfg = merge(cfg, _load_file(path))
    return validate(cfg)


def save_global(cfg: dict) -> Path:
    validate(cfg)
    path, _ = paths()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.mypa-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(cfg, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def update_global(overlay: dict) -> Path:
    # Project overrides must never be copied into global settings.
    global_path, local_path = paths()
    cfg = merge(merge(DEFAULTS, _load_file(global_path)), overlay)
    validate(merge(cfg, _load_file(local_path)))
    return save_global(cfg)


def public_config(cfg: dict) -> dict:
    result = copy.deepcopy(cfg)
    for provider in result['providers'].values():
        key = provider.get('api_key', '')
        if key and not re.fullmatch(r'\{env:[A-Za-z_][A-Za-z0-9_]*\}', key):
            provider['api_key'] = ''
            provider['key_configured'] = True
    return result
