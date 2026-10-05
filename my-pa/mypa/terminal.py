"""Dependency-free terminal presentation, with plain output for redirected streams."""
from contextlib import contextmanager
import os
import re
import shutil
import sys
import threading
import time


def clean(text):
    # Model/file/command output must not execute terminal control sequences.
    text = re.sub(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)', '', str(text))
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if c in '\n\t' or (ord(c) >= 32 and ord(c) != 127))


class Terminal:
    def __init__(self):
        self.color = sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
        self.animate = sys.stderr.isatty() and os.environ.get('TERM') != 'dumb'
        self.label = 'Connecting to Ollama'
        self.lock = threading.Lock()
        self.started = time.monotonic()

    def style(self, text, code):
        return f'\033[{code}m{text}\033[0m' if self.color else text

    def banner(self, cfg, version):
        print('\n' + self.style(f'  myPA  {version}  /  LOCAL AGENT', '1;36'))
        print('  ' + '-' * min(64, max(20, shutil.get_terminal_size().columns - 4)))
        print('  Model      ' + clean(cfg['default_model'].removeprefix('local/')))
        print('  Workspace  ' + clean(cfg['agent']['workspace']))
        print(f"  Context    {cfg['agent'].get('num_ctx', 4096)} tokens")
        print(self.style('  /help commands   /paste multiline   Ctrl+C cancel   /exit quit\n', '2'))

    def prompt(self):
        # Readline needs nonprinting markers around ANSI sequences.
        return '\001\033[1;36m\002you ›\001\033[0m\002 ' if self.color else 'you > '

    def help(self):
        print('\n  /clear           Clear screen, keep conversation\n  /clearsession    Clear conversation, tool results and input history\n  /new             Alias for /clearsession\n  /workspace PATH  Select a project\n  /model NAME      Select a local model for this session\n  /models          List installed Ollama models\n  /status          Show session settings\n  /tools           Inspect the last task activity\n  /stats           Show performance for the last task\n  /doctor          Diagnose dependencies, Ollama and model\n  /repair          Repair missing runtime dependencies and model\n  /evolve REQUEST  Develop and test improvements to myPA\n  /rollback        Restore the previous myPA source\n  /paste           Enter a multiline task, ending with .\n  /exit            Close myPA\n')

    def clear_screen(self):
        if sys.stdout.isatty() and os.environ.get('TERM') != 'dumb':
            sys.stdout.write('\033[2J\033[H')
            sys.stdout.flush()
        else:
            print()

    def stats(self, stats):
        if not stats:
            print('  No performance statistics for the last task.')
            return
        print(f"\n  Model requests  {stats.get('model_requests', 0)}")
        for label, key in [('Model loading', 'load_duration'), ('Prompt processing', 'prompt_eval_duration'), ('Generation', 'eval_duration')]:
            print(f"  {label:<18} {stats.get(key, 0) / 1_000_000_000:.2f}s")
        print(f"  Tool execution     {stats.get('tool_seconds', 0):.2f}s")
        duration = stats.get('eval_duration', 0)
        if duration:
            print(f"  Generation speed   {stats.get('eval_count', 0) * 1_000_000_000 / duration:.1f} tokens/s")
        print()

    def clear_line(self):
        if self.animate: sys.stderr.write('\r\033[2K')

    def event(self, event):
        with self.lock:
            if event['type'] == 'status':
                self.label = clean(event['text'])
                if not self.animate: print('  ' + self.label, file=sys.stderr, flush=True)
            elif event['type'] == 'tool':
                tool = event['event']
                self.clear_line()
                target = next((tool['arguments'].get(k) for k in ('path', 'command', 'query', 'url') if tool['arguments'].get(k)), '') if isinstance(tool['arguments'], dict) else ''
                print(f"  {'OK' if tool['ok'] else 'FAIL'}  {clean(tool['tool'])}  {clean(target).splitlines()[0][:100] if target else ''}", file=sys.stderr, flush=True)
                if not tool['ok']: print('      ' + clean(tool['result'])[:500], file=sys.stderr)
            elif event['type'] == 'token':
                self.label = 'Composing response'

    @contextmanager
    def activity(self):
        stop = threading.Event()
        def draw():
            frames = '|/-\\'
            index = 0
            while not stop.is_set():
                with self.lock:
                    width = max(10, shutil.get_terminal_size().columns - 3)
                    line = f'  {frames[index % 4]} {self.label} · {time.monotonic() - self.started:.0f}s'
                    sys.stderr.write('\r\033[2K' + line[:width])
                    sys.stderr.flush()
                index += 1
                stop.wait(0.1)
        thread = threading.Thread(target=draw, daemon=True) if self.animate else None
        if thread: thread.start()
        try: yield
        finally:
            stop.set()
            if thread: thread.join()
            self.clear_line()
            sys.stderr.flush()

    def reply(self, reply, elapsed, trace):
        print('\n' + self.style('  myPA', '1;36') + '\n')
        print(clean(reply))
        failed = sum(not item['ok'] for item in trace)
        print(self.style(f'\n  {elapsed:.1f}s · {len(trace)} tool calls · {failed} failed\n', '2'))

    def trace(self, trace):
        if not trace: print('  No tool activity for the last task.')
        for item in trace:
            print(f"\n  {'OK' if item['ok'] else 'FAIL'} {clean(item['tool'])}")
            print(clean(item['arguments']))
            print(clean(item['result']))

    def error(self, text):
        print('\n  Error: ' + clean(text) + '\n', file=sys.stderr)


def setup_readline():
    try:
        import readline
    except ImportError:
        return
    commands = ['/help', '/clear', '/clearsession', '/new', '/reset', '/workspace ', '/model ', '/models', '/status', '/tools', '/stats', '/doctor', '/repair', '/evolve ', '/rollback', '/paste', '/exit']
    def complete(text, state):
        matches = [command for command in commands if command.startswith(text)]
        return matches[state] if state < len(matches) else None
    readline.set_completer(complete)
    readline.parse_and_bind('tab: complete')
