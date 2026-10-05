"""Terminal interface for the local myPA agent."""
from __future__ import annotations
import argparse
import sys
import subprocess
import time
from . import __version__
from .config import load, paths, public_config, update_global
from pathlib import Path
from .terminal import Terminal, setup_readline


def cmd_chat(args):
    cfg = load()
    if getattr(args, 'workspace', None):
        workspace = Path(args.workspace).expanduser().resolve()
        if not workspace.is_dir(): raise ValueError('Workspace must be an existing directory')
        cfg['agent']['workspace'] = str(workspace)
    cfg['agent']['workspace'] = str(Path(cfg['agent']['workspace']).expanduser().resolve())
    ui = Terminal()
    ui.banner(cfg, __version__)
    setup_readline()
    last_result = {}
    hist: list[dict] = []
    if args.prompt:
        hist.append({"role": "user", "content": args.prompt})
        answer(cfg, hist, getattr(args, 'agent', False), stream=True)
        return
    while True:
        try:
            line = input(ui.prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("/exit", "/quit", "exit"):
            break
        if line == '/clear':
            ui.clear_screen()
            ui.banner(cfg, __version__)
            continue
        if line in ('/clearsession', '/new', '/reset'):
            hist.clear()
            last_result = {}
            try:
                import readline
                readline.clear_history()
            except ImportError:
                pass
            print('Session cleared. Model and workspace preserved.')
            continue
        if line == '/help':
            ui.help()
            continue
        if line == '/status':
            ui.banner(cfg, __version__)
            continue
        if line == '/tools':
            ui.trace(last_result.get('trace', []))
            continue
        if line == '/stats':
            ui.stats(last_result.get('stats', {}))
            continue
        if line in ('/doctor', '/repair', '/rollback') or line.startswith('/evolve '):
            try:
                from .maintenance import doctor, evolve, rollback
                if line in ('/doctor', '/repair'):
                    show_checks(doctor(fix=line == '/repair'))
                elif line == '/rollback':
                    print(rollback())
                else:
                    with ui.activity():
                        last_result = evolve(cfg, line[len('/evolve '):], on_event=ui.event)
                    print(last_result['reply'])
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
                ui.error(str(exc))
            except KeyboardInterrupt:
                ui.error('Self-development cancelled; staged changes were not applied.')
            continue
        if line == '/models':
            import requests
            try:
                response = requests.get(cfg['providers']['local']['base_url'].rstrip('/') + '/api/tags', timeout=10)
                try:
                    response.raise_for_status()
                    for model in response.json().get('models', []): print('  ' + model['name'])
                finally: response.close()
            except (requests.RequestException, ValueError, KeyError) as exc: ui.error(str(exc))
            continue
        if line == '/paste':
            print('Paste your task; enter a single . on a line to submit.')
            lines = []
            try:
                while True:
                    part = input('... ')
                    if part == '.': break
                    lines.append(part)
            except (KeyboardInterrupt, EOFError):
                print('Cancelled.')
                continue
            line = '\n'.join(lines).strip()
        if line.startswith('/model '):
            model = line.split(maxsplit=1)[1].strip()
            if model.startswith('local/'): model = model[len('local/'):]
            if not model:
                print('Use /model NAME for an installed local Ollama model')
                continue
            cfg['default_model'] = 'local/' + model
            hist.clear()
            print(f"Model: {cfg['default_model']}")
            continue
        if line.startswith('/') and not line.startswith('/workspace '):
            # Absolute project paths are requests, not slash commands.
            if not Path(line.split()[0]).is_dir():
                print('Unknown control. Type /help.')
                continue
        if line.startswith('/workspace '):
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
            results = []
            reply = answer(cfg, hist, getattr(args, 'agent', False), stream=True, on_result=results.append)
        except KeyboardInterrupt:
            hist.pop()
            continue
        except Exception as e:
            ui.error(str(e))
            hist.pop()
            continue
        item = {"role": "assistant", "content": reply}
        if results:
            last_result = results[-1]
            item['agent_context'] = last_result.get('context', '')
        hist.append(item)
        hist = hist[-100:]



def answer(cfg, messages, agent=True, stream=False, on_result=None):
    from .agent import run
    from .maintenance import learn, learned_hints
    ui = Terminal()
    cfg['agent']['learned_hints'] = learned_hints()
    started = time.monotonic()
    try:
        with ui.activity():
            result = run(cfg, messages, on_event=ui.event if stream else None, use_tools=True)
        cfg['agent']['workspace'] = result.get('workspace', cfg['agent']['workspace'])
        learn(result.get('trace', []))
        if on_result: on_result(result)
        if stream: ui.reply(result['reply'], time.monotonic() - started, result.get('trace', []))
        return result['reply']
    except KeyboardInterrupt:
        ui.error('Cancelled. You can enter another task.')
        raise


def cmd_config(args):
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


def show_checks(checks):
    for name, ok, detail in checks:
        print(f"  {'OK' if ok else 'FAIL'}  {name}: {detail}")
    return all(ok for _, ok, _ in checks)


def _main(argv=None):
    ap = argparse.ArgumentParser(prog="mypa", description="myPA — local terminal coding agent")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--workspace", help="project directory (defaults to current directory)")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser('agent', help='local agent with files, commands and web tools')
    a.add_argument('prompt', nargs='?', default=None)
    a.add_argument('--workspace', default=argparse.SUPPRESS, help='project directory for file tools and commands')
    a.set_defaults(agent=True)
    d = sub.add_parser('doctor', help='diagnose local installation; --fix repairs dependencies, Ollama and missing model')
    d.add_argument('--fix', action='store_true')
    e = sub.add_parser('evolve', help='develop and verify improvements to myPA using the local model')
    e.add_argument('request', help='the improvement or internal bug to fix')
    sub.add_parser('rollback', help='restore source from the last self-development backup')
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
    if args.cmd == 'doctor':
        from .maintenance import doctor
        if not show_checks(doctor(fix=args.fix)): raise SystemExit(1)
    elif args.cmd == 'evolve':
        from .maintenance import evolve
        ui = Terminal()
        with ui.activity(): result = evolve(load(), args.request, on_event=ui.event)
        print(result['reply'])
    elif args.cmd == 'rollback':
        from .maintenance import rollback
        print(rollback())
    elif args.cmd == "config":
        cmd_config(args)
    elif args.cmd == "rules":
        cmd_rules(args)
    elif args.cmd == "agent":
        cmd_chat(args)
    else:
        cmd_chat(argparse.Namespace(prompt=None, agent=True, workspace=args.workspace))


def main(argv=None):
    try:
        return _main(argv)
    except (ValueError, RuntimeError, OSError, IndexError, subprocess.SubprocessError) as exc:
        Terminal().error(str(exc))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
