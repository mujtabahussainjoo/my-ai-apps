import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mypa import config, rules

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
        config.update_global({'providers': {'openai': {'api_key': 'private', 'enabled': True, 'model': 'legacy-model'}}})
        self.local_path.write_text('{"theme":"mypa-light"}')
        config.update_global({'providers': {'openai': {'enabled': False}}})
        cfg = config.load()
        self.assertEqual(cfg['providers']['openai']['api_key'], 'private')
        self.assertEqual(cfg['providers']['openai']['model'], 'legacy-model')
        self.assertEqual(cfg['theme'], 'mypa-light')
        self.assertEqual(json.loads(self.global_path.read_text())['theme'], 'mypa-dark')
        if os.name != 'nt': self.assertEqual(self.global_path.stat().st_mode & 0o777, 0o600)
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
