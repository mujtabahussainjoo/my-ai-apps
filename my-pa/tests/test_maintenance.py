import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mypa import maintenance as m
from mypa.config import DEFAULTS


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'source'
        self.state = Path(self.temp.name) / 'state'
        (self.root / 'mypa').mkdir(parents=True)
        (self.root / 'tests').mkdir()
        (self.root / 'pyproject.toml').write_text('[project]\nname="test"\n')
        (self.root / 'mypa/__init__.py').write_text('')
        (self.root / 'mypa/__main__.py').write_text('print("test-version")\n')
        (self.root / 'mypa/feature.py').write_text('VALUE = 1\n')
        (self.root / 'tests/test_feature.py').write_text('import unittest\nfrom mypa.feature import VALUE\nclass FeatureTests(unittest.TestCase):\n def test_value(self): self.assertGreater(VALUE, 0)\n')
        self.patch = patch('mypa.maintenance.state_dir', return_value=self.state)
        self.patch.start()
    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def candidate(self):
        path = Path(self.temp.name) / 'candidate'
        m.copy_source(self.root, path)
        (path / 'mypa/feature.py').write_text('VALUE = 2\n')
        return path

    def test_apply_and_rollback(self):
        expected = m.signature(m.source_files(self.root))
        with m.maintenance_lock() as directory:
            changed = m.apply_candidate(self.root, self.candidate(), expected, directory)
        self.assertEqual(changed, ['mypa/feature.py'])
        self.assertIn('2', (self.root / 'mypa/feature.py').read_text())
        m.rollback(self.root)
        self.assertIn('1', (self.root / 'mypa/feature.py').read_text())

    def test_concurrent_changes_prevent_application(self):
        expected = m.signature(m.source_files(self.root))
        candidate = self.candidate()
        (self.root / 'mypa/feature.py').write_text('VALUE = 3\n')
        with m.maintenance_lock() as directory, self.assertRaisesRegex(RuntimeError, 'Source changed'):
            m.apply_candidate(self.root, candidate, expected, directory)
        self.assertIn('3', (self.root / 'mypa/feature.py').read_text())

    def test_failed_transaction_restores_source(self):
        expected = m.signature(m.source_files(self.root))
        candidate = self.candidate()
        (candidate / 'mypa/extra.py').write_text('ADDED = True\n')
        real_write = m.atomic_write
        count = 0
        def fail_once(path, data):
            nonlocal count
            count += 1
            if count == 3: raise OSError('disk error')
            return real_write(path, data)
        with m.maintenance_lock() as directory, patch('mypa.maintenance.atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError): m.apply_candidate(self.root, candidate, expected, directory)
        self.assertEqual(m.signature(m.source_files(self.root)), expected)

    def test_evolution_runs_original_and_candidate_tests(self):
        def develop(cfg, messages, on_event):
            (Path(cfg['agent']['workspace']) / 'mypa/feature.py').write_text('VALUE = 2\n')
            return {'trace':[{'ok':True}], 'reply':'Done'}
        with patch('mypa.agent.run', side_effect=develop):
            result = m.evolve(copy.deepcopy(DEFAULTS), 'Improve feature', root=self.root)
        self.assertEqual(result['changed'], ['mypa/feature.py'])
        self.assertIn('2', (self.root / 'mypa/feature.py').read_text())

    def test_broken_evolution_does_not_change_installation(self):
        expected = m.signature(m.source_files(self.root))
        def develop(cfg, messages, on_event):
            (Path(cfg['agent']['workspace']) / 'mypa/feature.py').write_text('VALUE = -1\n')
            return {'trace':[{'ok':True}], 'reply':'Done'}
        with patch('mypa.agent.run', side_effect=develop), self.assertRaisesRegex(RuntimeError, 'Verification failed'):
            m.evolve(copy.deepcopy(DEFAULTS), 'Improve feature', root=self.root)
        self.assertEqual(m.signature(m.source_files(self.root)), expected)

    def test_incomplete_evolution_is_not_applied(self):
        expected = m.signature(m.source_files(self.root))
        result = {'trace':[{'ok':True}], 'reply':'Agent reached its step limit. Review the activity log.'}
        with patch('mypa.agent.run', return_value=result), self.assertRaisesRegex(RuntimeError, 'step limit'):
            m.evolve(copy.deepcopy(DEFAULTS), 'Improve feature', root=self.root)
        self.assertEqual(m.signature(m.source_files(self.root)), expected)

    def test_learning_uses_fixed_hints_without_raw_content(self):
        m.learn([{'ok':False, 'result':'private file contents\nOld text must match exactly once'}])
        self.assertIn('exact unique text block', m.learned_hints())
        self.assertNotIn('private file', (self.state / 'lessons.json').read_text())

    def test_rollback_refuses_to_overwrite_later_edits(self):
        with m.maintenance_lock() as directory:
            m.apply_candidate(self.root, self.candidate(), m.signature(m.source_files(self.root)), directory)
        (self.root / 'mypa/feature.py').write_text('VALUE = 3\n')
        with self.assertRaisesRegex(ValueError, 'changed since'): m.rollback(self.root)

    @unittest.skipIf(__import__('os').name == 'nt', 'POSIX symlink test')
    def test_source_application_rejects_symlink_destination(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.root / 'mypa/new').symlink_to(outside, target_is_directory=True)
        files = m.source_files(self.root)
        files['mypa/new/escape.py'] = b'ESCAPE = True\n'
        with self.assertRaisesRegex(ValueError, 'escapes'):
            m.replace_source(self.root, files)
        self.assertFalse((outside / 'escape.py').exists())

    def test_doctor_preserves_invalid_config(self):
        with patch('mypa.config.load', side_effect=ValueError('invalid JSON')):
            checks = m.doctor()
        self.assertIn('invalid JSON', checks[-1][2])
        self.assertFalse(checks[-1][1])

    def test_doctor_reports_installed_model_without_downloading(self):
        import io
        cfg = copy.deepcopy(DEFAULTS)
        cfg['agent']['workspace'] = str(self.root)
        response = io.BytesIO(b'{"models":[{"name":"qwen2.5-coder:7b"}]}')
        with patch('mypa.config.load', return_value=cfg), patch('mypa.maintenance.urlopen', return_value=response), patch('mypa.maintenance.subprocess.run') as command:
            checks = m.doctor(fix=True)
        self.assertTrue(all(ok for _, ok, _ in checks))
        command.assert_not_called()
