"""Local diagnostics and tested, reversible source improvements."""
from __future__ import annotations
import copy
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from urllib.error import URLError


SOURCE_ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILES = ('README.md', 'pyproject.toml', 'MANIFEST.in', 'mypa.example.jsonc', 'install.py', 'install.sh', 'install.ps1')


def state_dir():
    if os.name == 'nt':
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
    else:
        root = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share')))
    return root / 'mypa'


def source_files(root):
    result = {}
    for folder in ('mypa', 'tests'):
        for path in (root / folder).rglob('*.py'):
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Source symlinks are not supported')
            result[str(path.relative_to(root))] = path.read_bytes()
    for name in SOURCE_FILES:
        path = root / name
        if path.is_symlink(): raise ValueError('Source symlinks are not supported')
        if path.is_file(): result[name] = path.read_bytes()
    return result


def copy_source(root, destination):
    for name, data in source_files(root).items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def signature(files):
    return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.mypa-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(data)
        if path.exists(): os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


@contextmanager
def maintenance_lock():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'maintenance.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError(f'Another maintenance operation is active. If it was interrupted, remove {path} after confirming no operation is running.') from None
    try:
        with os.fdopen(fd, 'w') as stream: stream.write(str(os.getpid()))
        yield directory
    finally:
        path.unlink(missing_ok=True)


def verify(candidate, baseline_tests=None):
    environment = os.environ.copy()
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    environment['PYTHONPATH'] = str(candidate)
    # Syntax checking does not emit cache files and includes all editable modules.
    for name, data in source_files(candidate).items():
        if name.endswith('.py'): compile(data, str(candidate / name), 'exec')
    if (candidate / 'install.sh').exists() and shutil.which('bash'):
        process = subprocess.run(['bash', '-n', str(candidate / 'install.sh')], capture_output=True, text=True, timeout=15)
        if process.returncode: raise RuntimeError('Installer syntax verification failed: ' + process.stderr)
    suites = [baseline_tests, candidate / 'tests'] if baseline_tests else [candidate / 'tests']
    if not any((candidate / 'tests').glob('test_*.py')):
        raise ValueError('A self-development installation needs its verification tests')
    for suite in suites:
        process = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(suite), '-q'],
                                 cwd=candidate, env=environment, capture_output=True, text=True, timeout=180)
        if process.returncode:
            raise RuntimeError('Verification failed:\n' + (process.stdout + process.stderr)[-12000:])
    process = subprocess.run([sys.executable, '-m', 'mypa', '--version'], cwd=candidate,
                             env=environment, capture_output=True, text=True, timeout=30)
    if process.returncode: raise RuntimeError('Candidate CLI failed: ' + process.stderr[-3000:])


def replace_source(root, files):
    current = source_files(root)
    for name in files:
        if not (root / name).resolve().is_relative_to(root.resolve()):
            raise ValueError('Source destination escapes installation')
    for name, data in files.items():
        if current.get(name) != data: atomic_write(root / name, data)
    for name in current.keys() - files.keys(): (root / name).unlink()


def apply_candidate(root, candidate, expected, directory):
    original = source_files(root)
    if signature(original) != expected: raise RuntimeError('Source changed during development; retry against the latest files')
    updated = source_files(candidate)
    changed = sorted(name for name in original.keys() | updated.keys() if original.get(name) != updated.get(name))
    if not changed: return []
    # Dependency and packaging changes need a separate installer run, not a live hot update.
    if original.get('pyproject.toml') != updated.get('pyproject.toml'):
        raise ValueError('Packaging/dependency changes require reinstalling; current source was not changed')
    backup = directory / 'backups' / (str(time.time_ns()))
    copy_source(root, backup)
    manifest = {'root': str(root.resolve()), 'before': signature(original), 'after': signature(updated), 'changed': changed}
    atomic_write(backup / 'manifest.json', json.dumps(manifest, indent=2).encode())
    try:
        replace_source(root, updated)
        atomic_write(directory / 'last-backup.json', json.dumps({'path': str(backup)}).encode())
    except BaseException:
        replace_source(root, original)
        raise
    return changed


def evolve(cfg, request, on_event=None, root=SOURCE_ROOT):
    from .agent import run
    root = root.resolve()
    if not (root / 'pyproject.toml').is_file() or not (root / 'tests').is_dir():
        raise ValueError('Self-development requires the source installation made by install.sh/install.ps1')
    with maintenance_lock() as directory, tempfile.TemporaryDirectory(prefix='mypa-evolve-') as temporary:
        candidate = Path(temporary) / 'candidate'
        baseline = Path(temporary) / 'baseline'
        original = source_files(root)
        copy_source(root, candidate)
        copy_source(root, baseline)
        expected = signature(original)
        verify(baseline)
        settings = copy.deepcopy(cfg)
        settings['agent']['workspace'] = str(candidate)
        prompt = ('Improve the myPA agent source in this workspace. Requested change: ' + request + '\n'
                  'Inspect the code, implement the change, and add meaningful regression tests. '
                  'Preserve existing features and permissions. Do not change packaging dependencies, '
                  'delete tests, modify the host installation, or launch long-running services. '
                  'Use the available installed dependencies. The host will run the original tests as well as your tests before applying changes.')
        result = run(settings, [{'role': 'user', 'content': prompt}], on_event=on_event)
        if not any(item['ok'] for item in result['trace']):
            raise RuntimeError('The local model did not execute a successful development tool; no changes applied')
        if not result['trace'][-1]['ok'] or result['reply'].startswith('Agent reached its step limit'):
            raise RuntimeError('Development ended with a failed tool or step limit; no changes applied. Retry with a smaller request.')
        if on_event: on_event({'type': 'status', 'text': 'Verifying original and updated test suites'})
        # Rebuild the original verification suite from the in-memory snapshot.
        replace_source(baseline, original)
        before_tests = {name for name in expected if name.startswith('tests/')}
        if not before_tests.issubset(source_files(candidate)):
            raise ValueError('Existing test files cannot be deleted during self-development')
        verify(candidate, baseline / 'tests')
        changed = apply_candidate(root, candidate, expected, directory)
        return {**result, 'changed': changed, 'reply': ('Applied tested improvements to ' + ', '.join(changed) + '. Restart mypa to load them.') if changed else 'No source changes were produced. Current installation preserved.'}


def rollback(root=SOURCE_ROOT):
    with maintenance_lock() as directory:
        pointer = directory / 'last-backup.json'
        if not pointer.exists(): raise ValueError('No self-development backup exists')
        backup = Path(json.loads(pointer.read_text())['path']).resolve()
        if not backup.is_relative_to((directory / 'backups').resolve()): raise ValueError('Invalid backup path')
        manifest = json.loads((backup / 'manifest.json').read_text())
        if manifest['root'] != str(root.resolve()): raise ValueError('Backup belongs to another installation')
        if signature(source_files(root)) != manifest['after']:
            raise ValueError('Source has changed since the last improvement; rollback would overwrite later changes')
        originals = source_files(backup)
        if signature(originals) != manifest['before']: raise ValueError('Backup verification failed')
        current = source_files(root)
        try: replace_source(root, originals)
        except BaseException:
            replace_source(root, current)
            raise
        pointer.unlink()
        return 'Previous source restored. Restart mypa.'


def doctor(fix=False):
    from .config import load
    checks = []
    if importlib.util.find_spec('requests') is None and fix:
        if sys.prefix == sys.base_prefix: raise ValueError('Dependency repair requires the installer virtual environment')
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'requests>=2.28'], check=True)
    present = importlib.util.find_spec('requests') is not None
    checks.append(('Python dependencies', present, 'Present' if present else 'Use the installer to restore dependencies'))
    try:
        cfg = load()
    except ValueError as exc:
        return checks + [('Configuration', False, str(exc) + '; configuration preserved for manual correction')]
    checks.append(('Configuration', True, 'Valid'))
    if not cfg['default_model'].startswith('local/') or not cfg['providers']['local'].get('enabled'):
        return checks + [('Local provider', False, 'Select and enable a local Ollama model in configuration')]
    base = cfg['providers']['local']['base_url'].rstrip('/')
    def tags():
        with urlopen(base + '/api/tags', timeout=5) as response: return json.load(response).get('models', [])
    try:
        models = tags()
    except (URLError, OSError, ValueError):
        if fix and base in ('http://127.0.0.1:11434', 'http://localhost:11434') and shutil.which('ollama'):
            log_path = state_dir() / 'ollama.log'
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open('ab') as log:
                subprocess.Popen(['ollama', 'serve'], stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 start_new_session=os.name != 'nt')
            for _ in range(30):
                time.sleep(0.5)
                try:
                    models = tags()
                    break
                except (URLError, OSError, ValueError): pass
            else: return checks + [('Ollama', False, f'Start failed; inspect {log_path}')]
        else: return checks + [('Ollama', False, 'Run the installer or start ollama serve')]
    checks.append(('Ollama', True, base))
    model = cfg['default_model'].removeprefix('local/')
    available = {entry.get('name') for entry in models}
    present = model in available or model + ':latest' in available
    if not present and fix and shutil.which('ollama'):
        environment = {**os.environ, 'OLLAMA_HOST': base}
        subprocess.run(['ollama', 'pull', model], env=environment, check=True)
        present = True
    checks.append(('Selected model', present, model))
    checks.append(('Workspace', Path(cfg['agent']['workspace']).expanduser().is_dir(), cfg['agent']['workspace']))
    return checks


LESSONS = {
    'Old text must match exactly once': 'Before edit_file, read the current file and select one exact unique text block.',
    'Path is outside': 'File tools require paths inside the workspace; inspect or switch the project first.',
    'Command timed out': 'Keep commands short; split expensive operations and inspect partial progress.',
    'externally-managed-environment': 'Install Python project dependencies in the project .venv.',
    'Destination already exists': 'Check move destinations before moving; do not overwrite existing paths.',
}


def learn(trace):
    found = {key for item in trace if not item.get('ok') for key in LESSONS if key in item.get('result', '')}
    if not found: return
    path = state_dir() / 'lessons.json'
    try:
        saved = json.loads(path.read_text()) if path.exists() else []
        keys = sorted((set(saved) | found) & LESSONS.keys())
        atomic_write(path, json.dumps(keys).encode())
    except (OSError, ValueError, TypeError): pass


def learned_hints():
    try:
        keys = json.loads((state_dir() / 'lessons.json').read_text())
        return ' '.join(LESSONS[key] for key in keys if isinstance(key, str) and key in LESSONS)[:600]
    except (OSError, ValueError, TypeError): return ''


def recovery_hint(error):
    return ' '.join(hint for key, hint in LESSONS.items() if key in error)
