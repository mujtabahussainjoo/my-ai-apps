"""myPA CLI — chat + web + config. Stdlib only (requests optional for live LLMs)."""
from __future__ import annotations
import argparse
import sys
import threading
import time
from contextlib import contextmanager
from . import __version__
from .config import load, paths, public_config, update_global
from .providers import chat


def cmd_chat(args):
    cfg = load()
    if getattr(args, 'workspace', None):
        from pathlib import Path
        workspace = Path(args.workspace).expanduser().resolve()
        if not workspace.is_dir(): raise ValueError('Workspace must be an existing directory')
        cfg['agent']['workspace'] = str(workspace)
    print(f"myPA v{__version__}  model={cfg.get('default_model')}  (type /exit)")
    hist: list[dict] = []
    if args.prompt:
        hist.append({"role": "user", "content": args.prompt})
        answer(cfg, hist, getattr(args, 'agent', False), stream=True)
        return
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("/exit", "/quit", "exit"):
            break
        if line.startswith('/workspace '):
            from pathlib import Path
            workspace = Path(line[len('/workspace '):]).expanduser().resolve()
            if not workspace.is_dir():
                print('[error] Workspace must be an existing directory', file=sys.stderr)
                continue
            cfg['agent']['workspace'] = str(workspace)
            hist.clear()
            print(f'Workspace: {workspace}')
            continue
        if not line:
            continue
        hist.append({"role": "user", "content": line})
        try:
            reply = answer(cfg, hist, getattr(args, 'agent', False), stream=True)
        except KeyboardInterrupt:
            hist.pop()
            continue
        except Exception as e:
            print(f"[error] {e}", file=sys.stderr)
            hist.pop()
            continue
        hist.append({"role": "assistant", "content": reply})



@contextmanager
def reply_loader():
    """Animate on stderr only in a terminal; always clean up before output."""
    stream = sys.stderr
    if not stream.isatty():
        yield
        return
    stopped = threading.Event()
    started = time.monotonic()
    label = 'myPA is working…'

    def animate():
        frames = '|/-\\'
        index = 0
        while not stopped.is_set():
            elapsed = int(time.monotonic() - started)
            stream.write(f'\r{frames[index % len(frames)]} {label} {elapsed}s')
            stream.flush()
            index += 1
            stopped.wait(0.1)

    thread = threading.Thread(target=animate, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()
        width = len(label) + len(str(int(time.monotonic() - started))) + 5
        stream.write('\r' + ' ' * width + '\r')
        stream.flush()


def answer(cfg, messages, agent=False, stream=False):
    if stream and cfg['default_model'].startswith('local/'):
        from .agent import run
        started = time.monotonic()
        writing = False
        def event(item):
            nonlocal writing
            if item['type'] == 'token':
                if not writing:
                    print('myPA> ', end='', flush=True)
                    writing = True
                print(item['text'], end='', flush=True)
            elif item['type'] == 'status':
                print(f"[{item['text']} · {time.monotonic() - started:.0f}s]", file=sys.stderr, flush=True)
            elif item['type'] == 'reset':
                if writing: print(flush=True)
                writing = False
            elif item['type'] == 'tool':
                tool = item['event']
                print(f"[{tool['tool']}] {tool['result'][:500]}", file=sys.stderr, flush=True)
        try:
            result = run(cfg, messages, on_event=event, use_tools=agent)
            if not writing: print(f"myPA> {result['reply']}", end='')
            print('\n', flush=True)
            return result['reply']
        except KeyboardInterrupt:
            print('\n[Cancelled]', file=sys.stderr)
            raise
    with reply_loader():
        if not agent:
            reply = chat(cfg, messages)
            if stream: print(f'myPA> {reply}\n')
            return reply
        from .agent import run
        result = run(cfg, messages)
    for item in result['trace']:
        print(f"[{item['tool']}] {item['result'][:500]}", file=sys.stderr)
    if stream: print(f"myPA> {result['reply']}\n")
    return result['reply']


def cmd_config(args):
    from .config import save_global
    import json
    cfg = load()
    if args.show:
        print(json.dumps(public_config(cfg), indent=2))
        g, l = paths()
        print(f"\nglobal: {g}\nlocal:  {l}")
    elif args.set_default:
        p = update_global({"default_model": args.set_default})
        print(f"default_model -> {args.set_default} (saved {p})")
    else:
        print("use --show or --set-default provider/model")


def cmd_rules(args):
    import json
    from . import rules as R
    if args.add:
        action, resource, effect = args.add
        print(json.dumps(R.add_rule(action, resource, effect), indent=2))
    elif args.remove is not None:
        print(json.dumps(R.remove_rule(args.remove), indent=2))
    elif args.clear:
        print(json.dumps(R.clear_rules(), indent=2))
    else:
        print(json.dumps(R.list_rules(), indent=2))


def _main(argv=None):
    ap = argparse.ArgumentParser(prog="mypa", description="myPA - Personal AI")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--web", action="store_true", help="alias for web")
    ap.add_argument("--port", type=int, default=3210)
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("chat", help="terminal chat")
    c.add_argument("prompt", nargs="?", default=None)
    a = sub.add_parser('agent', help='local agent with files, commands and web tools')
    a.add_argument('prompt', nargs='?', default=None)
    a.add_argument('--workspace', help='project directory for file tools and commands')
    a.set_defaults(agent=True)
    w = sub.add_parser("web", help="launch web UI")
    w.add_argument("--port", type=int, default=3210)
    g = sub.add_parser("config", help="view/set config")
    g.add_argument("--show", action="store_true")
    g.add_argument("--set-default", default=None)
    r = sub.add_parser("rules", help="custom allow/deny rules (empty by default)")
    r.add_argument("--list", action="store_true")
    r.add_argument("--add", nargs=3, metavar=("ACTION", "RESOURCE", "EFFECT"),
                   help='e.g. --add shell "rm *" deny')
    r.add_argument("--remove", type=int, metavar="INDEX")
    r.add_argument("--clear", action="store_true")
    args = ap.parse_args(argv)
    if args.version:
        print(__version__)
        return
    if args.cmd == "web" or args.web:
        from .server import serve
        serve(args.port)
    elif args.cmd == "config":
        cmd_config(args)
    elif args.cmd == "rules":
        cmd_rules(args)
    elif args.cmd in ("chat", "agent"):
        cmd_chat(args)
    else:
        cmd_chat(argparse.Namespace(prompt=None))


def main(argv=None):
    try:
        return _main(argv)
    except (ValueError, RuntimeError, OSError, IndexError) as exc:
        print(f"myPA: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
