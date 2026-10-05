"""Loopback web UI and validated JSON API."""
from __future__ import annotations
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from .config import load, public_config, update_global
from .providers import chat

WEB_DIR = Path(__file__).resolve().parent / 'web'
if not WEB_DIR.exists():
    WEB_DIR = Path(__file__).resolve().parent.parent / 'web'
LOCK = threading.RLock()
MAX_BODY = 1024 * 1024


class H(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _trusted(self):
        port = self.server.server_address[1]
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host', '') not in hosts:
            self._json({'error': 'Invalid host'}, 403)
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {f'http://{host}' for host in hosts}:
            self._json({'error': 'Invalid origin'}, 403)
            return False
        return True

    def do_POST(self):
        if not self._trusted():
            return
        endpoint = urlparse(self.path).path
        if endpoint not in ('/api/chat', '/api/agent', '/api/agent/stream', '/api/config', '/api/rules'):
            return self._json({'error': 'Unknown endpoint'}, 404)
        if self.headers.get_content_type() != 'application/json':
            return self._json({'error': 'Use application/json'}, 415)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_BODY:
                return self._json({'error': 'Body must be between 1 byte and 1 MiB'}, 413)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Body must be an object')
            if endpoint == '/api/agent/stream':
                from .agent import run
                from .providers import validate_messages
                cfg = load()
                validate_messages(data.get('messages'))
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                def emit(event):
                    self.wfile.write((json.dumps(event) + '\n').encode())
                    self.wfile.flush()
                try:
                    result = run(cfg, data['messages'], on_event=emit, use_tools=data.get('mode') != 'chat')
                    emit({'type': 'done', **result})
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except (RuntimeError, ValueError, OSError) as exc:
                    try: emit({'type': 'error', 'error': str(exc)})
                    except (BrokenPipeError, ConnectionResetError): pass
                return
            if endpoint == '/api/agent':
                from .agent import run
                return self._json(run(load(), data.get('messages')))
            if endpoint == '/api/chat':
                cfg = load()
                return self._json({'reply': chat(cfg, data.get('messages')), 'model': cfg['default_model']})
            with LOCK:
                if endpoint == '/api/config':
                    # Ignore UI metadata; blank keys mean preserve existing keys.
                    if not isinstance(data.get('providers', {}), dict):
                        raise ValueError('providers must be an object')
                    for provider in data.get('providers', {}).values():
                        if isinstance(provider, dict):
                            provider.pop('key_configured', None)
                            if not provider.get('api_key'):
                                provider.pop('api_key', None)
                    path = update_global(data)
                    return self._json({'ok': True, 'saved': str(path), 'config': public_config(load())})
                from . import rules
                operation = data.get('op', 'list')
                if operation == 'add':
                    value = rules.add_rule(data['action'], data['resource'], data['effect'])
                elif operation == 'remove':
                    value = rules.remove_rule(data['index'])
                elif operation == 'clear':
                    value = rules.clear_rules()
                elif operation == 'list':
                    value = rules.list_rules()
                else:
                    raise ValueError('Unknown rules operation')
                return self._json({'permissions': value})
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            return self._json({'error': str(exc)}, 400)
        except RuntimeError as exc:
            return self._json({'error': str(exc)}, 502)
        except OSError:
            return self._json({'error': 'Unable to access configuration or provider'}, 500)

    def do_GET(self):
        if not self._trusted():
            return
        endpoint = urlparse(self.path).path
        try:
            if endpoint == '/api/health':
                return self._json({'ok': True, 'app': 'myPA'})
            if endpoint == '/api/models':
                import requests
                cfg = load()
                try:
                    response = requests.get(cfg['providers']['local']['base_url'].rstrip('/') + '/api/tags', timeout=5)
                    response.raise_for_status()
                    return self._json({'models': response.json().get('models', [])})
                except (requests.RequestException, ValueError):
                    return self._json({'error': 'Cannot reach Ollama; start ollama serve'}, 502)
            if endpoint == '/api/config':
                return self._json(public_config(load()))
            if endpoint == '/api/rules':
                return self._json({'permissions': load()['permissions']})
            if endpoint.startswith('/api/'):
                return self._json({'error': 'Unknown endpoint'}, 404)
            if endpoint.endswith('/') and endpoint != '/':
                return self._json({'error': 'Directory listing disabled'}, 404)
            return super().do_GET()
        except (ValueError, OSError):
            return self._json({'error': 'Unable to load configuration; check your JSONC files'}, 500)

    def list_directory(self, path):
        return self._json({'error': 'Directory listing disabled'}, 404)


def serve(port=3210):
    with ThreadingHTTPServer(('127.0.0.1', port), H) as server:
        print(f'myPA web at http://127.0.0.1:{server.server_address[1]}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
