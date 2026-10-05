"""Live provider adapters; failures never masquerade as model responses."""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
try:
    import requests
except ImportError:
    requests = None


def _resolve(value):
    if not value:
        return value
    match = re.fullmatch(r'\{env:([A-Za-z_][A-Za-z0-9_]*)\}', value.strip())
    return os.environ.get(match[1]) if match else value


def validate_messages(messages):
    if not isinstance(messages, list) or not messages or len(messages) > 200:
        raise ValueError('Provide 1–200 chat messages')
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in ('system', 'user', 'assistant') or not isinstance(message.get('content'), str) or not message['content'].strip():
            raise ValueError('Each message needs a valid role and nonempty text content')
    if messages[-1]['role'] != 'user':
        raise ValueError('The last message must be from the user')


def chat(cfg, messages):
    validate_messages(messages)
    provider, model = cfg['default_model'].split('/', 1)
    settings = cfg['providers'].get(provider, {})
    if not settings.get('enabled'):
        raise ValueError(f'{provider} is disabled; enable it in Settings')
    if provider == 'opencode':
        return _opencode(cfg, messages)
    if requests is None:
        raise RuntimeError('Install myPA dependencies: python -m pip install -e .')
    key = _resolve(settings.get('api_key'))
    if provider in ('openai', 'anthropic') and not key:
        raise ValueError(f'{provider} API key is missing; configure it in Settings or the environment')
    try:
        if provider == 'openai':
            response = requests.post('https://api.openai.com/v1/chat/completions', headers={'Authorization': f'Bearer {key}'}, json={'model': model, 'messages': messages}, timeout=60)
        elif provider == 'anthropic':
            payload = {'model': model, 'max_tokens': 2048, 'messages': [m for m in messages if m['role'] != 'system']}
            system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
            if system:
                payload['system'] = system
            response = requests.post('https://api.anthropic.com/v1/messages', headers={'x-api-key': key, 'anthropic-version': '2023-06-01'}, json=payload, timeout=60)
        elif provider == 'local':
            base = settings.get('base_url', 'http://127.0.0.1:11434').rstrip('/')
            response = requests.post(f'{base}/api/chat', json={'model': model, 'messages': messages, 'stream': False}, timeout=120)
        else:
            raise ValueError(f'Unsupported provider: {provider}')
        response.raise_for_status()
        data = response.json()
        if provider == 'openai':
            reply = data['choices'][0]['message']['content']
        elif provider == 'anthropic':
            reply = ''.join(block.get('text', '') for block in data['content'] if block.get('type') == 'text')
        else:
            reply = data['message']['content']
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError('Empty provider response')
        return reply
    except requests.RequestException as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        raise RuntimeError(f'{provider} request failed' + (f' (HTTP {status})' if status else '; check connection and provider availability')) from None
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError(f'{provider} returned an invalid or empty response') from None


def _opencode(cfg, messages):
    executable = shutil.which('opencode')
    if not executable:
        raise RuntimeError('OpenCode is not installed. Install it from https://opencode.ai or select another provider in Settings.')
    permission = {'*': 'deny'}
    for rule in cfg.get('permissions', []):
        action = {'shell': 'bash', 'write': 'edit'}.get(rule['action'], rule['action'])
        effect = 'deny' if rule['effect'] == 'ask' else rule['effect']
        if rule['resource'] == '*':
            permission[action] = effect
        else:
            previous = permission.get(action, permission.get('*', 'deny'))
            if isinstance(previous, str):
                previous = {'*': previous}
            previous.pop(rule['resource'], None)
            previous[rule['resource']] = effect
            permission[action] = previous
    environment = os.environ.copy()
    environment['OPENCODE_CONFIG_CONTENT'] = json.dumps({'agent': {'mypa': {'mode': 'primary', 'description': 'myPA conversation', 'permission': permission}}})
    prompt = 'Conversation history (respond to the final user message):\n' + json.dumps(messages, ensure_ascii=False)
    try:
        result = subprocess.run([executable, 'run', '--format', 'json', '--model', cfg['default_model'], '--agent', 'mypa', '--', prompt], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180, env=environment)
    except subprocess.TimeoutExpired:
        raise RuntimeError('OpenCode timed out') from None
    if result.returncode:
        raise RuntimeError('OpenCode failed; check provider authentication and run opencode models to verify the selected model')
    parts = []
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'error':
            raise RuntimeError('OpenCode reported a provider error; check authentication and selected model')
        if event.get('type') == 'text':
            parts.append(event.get('part', {}).get('text', ''))
    if not parts:
        raise RuntimeError('OpenCode returned no text response')
    return ''.join(parts)
