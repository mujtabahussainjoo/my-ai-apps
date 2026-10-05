#!/usr/bin/env python3
"""Single-command, per-user myPA installation after native Python bootstrap."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from urllib.error import URLError


def execute(command, **kwargs):
    print('  > ' + ' '.join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, **kwargs)


def default_prefix():
    if os.name == 'nt': return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'mypa'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'mypa'


def install_ollama(system, directory):
    if shutil.which('ollama'): return
    if system in ('Linux', 'Darwin'):
        target = directory / 'ollama-install.sh'
        with urlopen('https://ollama.com/install.sh', timeout=60) as response: target.write_bytes(response.read())
        execute(['sh', target])
    elif system == 'Windows':
        target = directory / 'ollama-install.ps1'
        with urlopen('https://ollama.com/install.ps1', timeout=60) as response: target.write_bytes(response.read())
        execute(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', target])
        location = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama'
        os.environ['PATH'] = str(location) + os.pathsep + os.environ.get('PATH', '')
    else: raise RuntimeError(f'Automatic Ollama installation is unsupported on {system}')
    if not shutil.which('ollama'): raise RuntimeError('Ollama installation completed but the command was not found')


def ensure_server(prefix, base):
    def available():
        try:
            with urlopen(base + '/api/tags', timeout=3) as response: json.load(response)
            return True
        except (URLError, ValueError, OSError): return False
    if available(): return
    if base not in ('http://127.0.0.1:11434', 'http://localhost:11434'):
        raise RuntimeError('Configured remote Ollama is unavailable; local installation will not replace it')
    with (prefix / 'ollama.log').open('ab') as output:
        environment = {**os.environ, 'OLLAMA_HOST': base}
        subprocess.Popen(['ollama', 'serve'], env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                         start_new_session=os.name != 'nt', creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
    for _ in range(60):
        if available(): return
        time.sleep(0.5)
    raise RuntimeError(f'Ollama did not start. Inspect {prefix / "ollama.log"}')


def write_launcher(python, destination, windows=False):
    destination.mkdir(parents=True, exist_ok=True)
    if windows:
        path = destination / 'mypa.cmd'
        path.write_text(f'@echo off\nset PYTHONDONTWRITEBYTECODE=1\n"{python}" -m mypa %*\n')
    else:
        path = destination / 'mypa'
        path.write_text('#!/bin/sh\nPYTHONDONTWRITEBYTECODE=1 exec ' + shlex.quote(str(python)) + ' -m mypa "$@"\n')
        path.chmod(0o755)
    return path


def add_path(destination):
    if os.name == 'nt':
        # Use the registry directly rather than setx, which can truncate long PATHs.
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            try: value, kind = winreg.QueryValueEx(key, 'Path')
            except FileNotFoundError: value, kind = '', winreg.REG_EXPAND_SZ
            if str(destination).casefold() not in [part.casefold() for part in value.split(';')]:
                winreg.SetValueEx(key, 'Path', 0, kind, str(destination) + ';' + value)
    else:
        line = '\n# myPA terminal agent\nexport PATH=' + shlex.quote(str(destination)) + ':"$PATH"\n'
        files = [Path.home() / '.profile', Path.home() / '.bashrc']
        if platform.system() == 'Darwin' or 'zsh' in os.environ.get('SHELL', ''): files.append(Path.home() / '.zshrc')
        for path in files:
            content = path.read_text() if path.exists() else ''
            if line.strip() not in content:
                with path.open('a') as stream: stream.write(line)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install myPA and all required dependencies for this user')
    parser.add_argument('--prefix', type=Path, default=default_prefix())
    parser.add_argument('--bin-dir', type=Path)
    parser.add_argument('--model', help='local Ollama model (preserves existing model by default)')
    parser.add_argument('--dry-run', action='store_true', help='show steps without installing or downloading')
    parser.add_argument('--no-path', action='store_true', help='do not modify shell startup files or Windows PATH')
    args = parser.parse_args(argv)
    system = platform.system()
    if system not in ('Linux', 'Darwin', 'Windows'): raise RuntimeError('Supported platforms: Linux, macOS, Windows')
    if sys.version_info < (3, 10): raise RuntimeError('Python 3.10+ is required; use the native bootstrap script')
    prefix = args.prefix.expanduser().resolve()
    binaries = (args.bin_dir or (prefix / 'bin' if os.name == 'nt' else Path.home() / '.local' / 'bin')).expanduser().resolve()
    if args.dry_run:
        print(f'Platform: {system}\nInstall: {prefix}\nCommand: {binaries / ("mypa.cmd" if os.name == "nt" else "mypa")}')
        print('Steps: create source release and virtual environment; install Python dependencies; install/start Ollama if missing; pull selected model; preserve config; install launcher and PATH; verify CLI.')
        return
    from mypa.config import DEFAULTS, _load_file, merge, paths, save_global
    from mypa.maintenance import copy_source
    cfg = merge(DEFAULTS, _load_file(paths()[0]))
    selected = args.model or (cfg['default_model'].split('/', 1)[1] if cfg['default_model'].startswith('local/') else 'qwen2.5-coder:7b')
    cfg['default_model'] = 'local/' + selected.removeprefix('local/')
    cfg['providers']['local']['enabled'] = True
    cfg['providers']['local']['model'] = cfg['default_model'].split('/', 1)[1]
    base = cfg['providers']['local']['base_url'].rstrip('/')
    prefix.mkdir(parents=True, exist_ok=True)
    release = prefix / 'releases' / str(time.time_ns())
    copy_source(Path(__file__).resolve().parent, release)
    venv = prefix / 'venv'
    python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists(): execute([sys.executable, '-m', 'venv', venv])
    execute([python, '-m', 'pip', 'install', '--upgrade', 'pip'])
    execute([python, '-m', 'pip', 'install', '-e', release])
    # Existing Ollama services and downloaded models are reused.
    if base in ('http://127.0.0.1:11434', 'http://localhost:11434'):
        with tempfile.TemporaryDirectory() as temporary: install_ollama(system, Path(temporary))
    ensure_server(prefix, base)
    model = cfg['providers']['local']['model']
    with urlopen(base + '/api/tags', timeout=10) as response: available = {item['name'] for item in json.load(response).get('models', [])}
    if model not in available and model + ':latest' not in available:
        if not shutil.which('ollama'): raise RuntimeError('ollama CLI is required to download the configured model')
        execute(['ollama', 'pull', model], env={**os.environ, 'OLLAMA_HOST': base})
    save_global(cfg)
    execute([python, '-m', 'mypa', '--version'], cwd=prefix)
    launcher = write_launcher(python, binaries, os.name == 'nt')
    if not args.no_path: add_path(binaries)
    (prefix / 'installation.json').write_text(json.dumps({'source': str(release), 'python': str(python), 'launcher': str(launcher)}, indent=2))
    print(f'\nInstalled. Open a new terminal and run mypa.\nRun immediately: {launcher}\nModel: {model}')


if __name__ == '__main__':
    try: main()
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('Installation failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
