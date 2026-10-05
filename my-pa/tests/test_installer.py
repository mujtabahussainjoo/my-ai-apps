import importlib.util
import io
import os
import shlex
from pathlib import Path
import tempfile
from contextlib import redirect_stdout
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('mypa_bootstrap', Path(__file__).resolve().parents[1] / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_dry_run_makes_no_changes(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(installer, 'execute') as execute, redirect_stdout(io.StringIO()):
            prefix = Path(temporary) / 'install'
            installer.main(['--dry-run', '--prefix', str(prefix)])
            self.assertFalse(prefix.exists())
            execute.assert_not_called()

    def test_launcher_preserves_directory_and_quotes_spaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = installer.write_launcher(Path('/example path/venv/bin/python'), Path(temporary))
            content = target.read_text()
        self.assertNotIn('cd ', content)
        self.assertIn(shlex.quote(str(Path('/example path/venv/bin/python'))), content)
        self.assertIn('"$@"', content)

    def test_windows_launcher_forwards_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = installer.write_launcher(Path('C:/Example Path/python.exe'), Path(temporary), windows=True)
            self.assertIn('%*', target.read_text())

    def test_existing_ollama_is_reused(self):
        with patch.object(installer.shutil, 'which', return_value='/usr/bin/ollama'), patch.object(installer, 'execute') as execute:
            installer.install_ollama('Linux', Path('/tmp'))
        execute.assert_not_called()
