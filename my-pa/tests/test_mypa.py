import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from mypa import config, providers, rules
from mypa.cli import main
from mypa.server import H

class ConfigFixture:

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.global_path = Path(self.temp.name) / 'global.jsonc'
        self.local_path = Path(self.temp.name) / 'local.jsonc'
        self.patcher = patch('mypa.config.paths', return_value=(self.global_path, self.local_path))
        self.patcher.start()
    def tearDown(self):
        self.patcher.stop(); self.temp.cleanup()

class ConfigurationTests(ConfigFixture, unittest.TestCase):
    def test_jsonc_preserves_strings_and_supports_comments(self):
        text = '{"url":"https://example.org/*hi*/", // inline\n "values":[1,2,], /* block */}'
        self.assertEqual(json.loads(config._strip_jsonc(text)), {'url':'https://example.org/*hi*/', 'values':[1,2]})
    def test_nested_update_preserves_credentials_and_project_scope(self):
        config.update_global({'providers': {'openai': {'api_key': 'private', 'enabled': True}}})
        self.local_path.write_text('{"theme":"mypa-light"}')
        config.update_global({'providers': {'openai': {'enabled': False}}})
        cfg = config.load()
        self.assertEqual(cfg['providers']['openai']['api_key'], 'private')
        self.assertEqual(cfg['providers']['openai']['model'], 'gpt-4o-mini')
        self.assertEqual(cfg['theme'], 'mypa-light')
        self.assertEqual(json.loads(self.global_path.read_text())['theme'], 'mypa-dark')
        self.assertEqual(self.global_path.stat().st_mode & 0o777, 0o600)
    def test_invalid_config_is_reported(self):
        self.global_path.write_text('{bad')
        with self.assertRaises(ValueError): config.load()
    def test_rules_roundtrip_and_bad_index(self):
        self.assertEqual(rules.add_rule('shell', 'rm *', 'deny')[0]['effect'], 'deny')
        with self.assertRaises(ValueError): rules.remove_rule(-1)
        self.assertEqual(rules.remove_rule(0), [])
    def test_keys_redacted(self):
        cfg = config.merge(config.DEFAULTS, {'providers': {'openai': {'api_key': 'secret'}}})
        public = config.public_config(cfg)
        self.assertEqual(public['providers']['openai']['api_key'], '')
        self.assertEqual(cfg['providers']['openai']['api_key'], 'secret')
    def test_cli_web_alias(self):
        with patch('mypa.server.serve') as serve:
            main(['--web', '--port', '4567']); serve.assert_called_once_with(4567)
        with patch('mypa.server.serve') as serve:
            main(['web', '--port', '4568']); serve.assert_called_once_with(4568)

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.messages = [{'role':'system','content':'Be brief'}, {'role':'user','content':'Hello'}, {'role':'assistant','content':'Hi'}, {'role':'user','content':'Continue'}]
    def cfg(self, name):
        cfg = copy.deepcopy(config.DEFAULTS); cfg['default_model'] = name + '/chosen-model'
        cfg['providers'][name].update(enabled=True, api_key='test-key')
        return cfg
    def test_openai_uses_selected_model_and_history(self):
        with patch.object(providers.requests, 'post') as post:
            post.return_value.json.return_value = {'choices':[{'message':{'content':'reply'}}]}
            self.assertEqual(providers.chat(self.cfg('openai'), self.messages), 'reply')
            self.assertEqual(post.call_args.kwargs['json'], {'model':'chosen-model','messages':self.messages})
    def test_anthropic_preserves_roles(self):
        with patch.object(providers.requests, 'post') as post:
            post.return_value.json.return_value = {'content':[{'type':'text','text':'reply'}]}
            providers.chat(self.cfg('anthropic'), self.messages)
            body = post.call_args.kwargs['json']
            self.assertEqual(body['system'], 'Be brief'); self.assertEqual(body['messages'], self.messages[1:])
    def test_ollama_chat(self):
        with patch.object(providers.requests, 'post') as post:
            post.return_value.json.return_value = {'message':{'content':'reply'}}
            providers.chat(self.cfg('local'), self.messages)
            self.assertTrue(post.call_args.args[0].endswith('/api/chat'))
            self.assertEqual(post.call_args.kwargs['json']['messages'], self.messages)
    def test_missing_disabled_invalid(self):
        with self.assertRaises(ValueError): providers.chat(config.DEFAULTS, [])
        cfg = self.cfg('openai'); cfg['providers']['openai']['enabled'] = False
        with self.assertRaises(ValueError): providers.chat(cfg, self.messages)
        cfg['providers']['openai'].update(enabled=True, api_key='')
        with self.assertRaises(ValueError): providers.chat(cfg, self.messages)
    def test_opencode_events_permissions_and_no_shell(self):
        cfg = self.cfg('opencode'); cfg['permissions'] = [{'action':'shell','resource':'rm *','effect':'deny'}, {'action':'read','resource':'*','effect':'ask'}]
        with patch('mypa.providers.shutil.which', return_value='/bin/opencode'), patch('mypa.providers.subprocess.run') as run:
            run.return_value = Mock(returncode=0, stdout='{"type":"text","part":{"text":"hello"}}\n{"type":"text","part":{"text":" world"}}')
            self.assertEqual(providers.chat(cfg, self.messages), 'hello world')
            self.assertNotIn('shell', run.call_args.kwargs)
            settings = json.loads(run.call_args.kwargs['env']['OPENCODE_CONFIG_CONTENT'])
            self.assertEqual(settings['agent']['mypa']['permission']['bash']['rm *'], 'deny')
            self.assertEqual(settings['agent']['mypa']['permission']['read'], 'deny')
    def test_opencode_missing_is_error(self):
        with patch('mypa.providers.shutil.which', return_value=None), self.assertRaises(RuntimeError):
            providers.chat(self.cfg('opencode'), self.messages)

class ApiTests(ConfigFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); super().tearDown()
    def request(self, path, body=None, headers=None):
        request = Request(self.url+path, data=body, headers=headers or {})
        try:
            with urlopen(request) as response: return response.status, response.read()
        except HTTPError as error: return error.code, error.read()
    def test_health_and_assets(self):
        for path in ('/', '/settings.html', '/app.js', '/api.js', '/settings.js', '/styles.css', '/api/health'):
            self.assertEqual(self.request(path)[0], 200)
    def test_errors_and_origin(self):
        headers={'Content-Type':'application/json'}
        self.assertEqual(self.request('/api/chat', b'bad', headers)[0], 400)
        self.assertEqual(self.request('/api/chat', b'[]', headers)[0], 400)
        self.assertEqual(self.request('/api/config', b'{"providers": []}', headers)[0], 400)
        self.assertEqual(self.request('/api/rules', b'{"op":"add","action":"read","resource":"*","effect":3}', headers)[0], 400)
        self.assertEqual(self.request('/api/chat', b'{}', headers)[0], 400)
        self.assertEqual(self.request('/api/chat', b'{}', {'Content-Type':'text/plain'})[0], 415)
        self.assertEqual(self.request('/api/config', b'{}', {**headers, 'Origin':'https://other.example'})[0], 403)
        self.assertEqual(self.request('/api/config', headers={'Host':'other.example'})[0], 403)
    def test_settings_keys_and_merge(self):
        headers={'Content-Type':'application/json'}
        payload={'providers':{'openai':{'enabled':True,'api_key':'secret'}}}
        self.assertEqual(self.request('/api/config', json.dumps(payload).encode(), headers)[0], 200)
        self.assertNotIn(b'secret', self.request('/api/config')[1])
        payload={'providers':{'openai':{'enabled':False,'api_key':''}}}
        self.assertEqual(self.request('/api/config', json.dumps(payload).encode(), headers)[0], 200)
        self.assertEqual(config.load()['providers']['openai']['api_key'], 'secret')
    def test_chat_error_and_success(self):
        body = json.dumps({'messages':[{'role':'user','content':'Hello'}]}).encode()
        with patch('mypa.server.chat', return_value='Hi'):
            status, data = self.request('/api/chat', body, {'Content-Type':'application/json'})
            self.assertEqual(status, 200); self.assertEqual(json.loads(data)['reply'], 'Hi')
        with patch('mypa.server.chat', side_effect=RuntimeError('Provider unavailable')):
            self.assertEqual(self.request('/api/chat', body, {'Content-Type':'application/json'})[0], 502)

if __name__ == '__main__': unittest.main()
