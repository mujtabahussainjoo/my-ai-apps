"""myPA CLI — chat + web + config. Stdlib only (requests optional for live LLMs)."""
from __future__ import annotations
import argparse
import sys
from . import __version__
from .config import load, paths
from .providers import chat


def cmd_chat(args):
    cfg = load()
    print(f"myPA v{__version__}  model={cfg.get('default_model')}  (type /exit)")
    hist: list[dict] = []
    if args.prompt:
        hist.append({"role": "user", "content": args.prompt})
        print(chat(cfg, hist))
        return
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("/exit", "/quit", "exit"):
            break
        if not line:
            continue
        hist.append({"role": "user", "content": line})
        try:
            reply = chat(cfg, hist)
        except Exception as e:
            reply = f"[error] {e}"
        hist.append({"role": "assistant", "content": reply})
        print(f"myPA> {reply}\n")


def cmd_config(args):
    from .config import save_global
    import json
    cfg = load()
    if args.show:
        print(json.dumps(cfg, indent=2))
        g, l = paths()
        print(f"\nglobal: {g}\nlocal:  {l}")
    elif args.set_default:
        cfg["default_model"] = args.set_default
        p = save_global(cfg)
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mypa", description="myPA - Personal AI")
    ap.add_argument("--version", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("chat", help="terminal chat")
    c.add_argument("prompt", nargs="?", default=None)
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
    if args.cmd == "web":
        from .server import serve
        serve(args.port)
    elif args.cmd == "config":
        cmd_config(args)
    elif args.cmd == "rules":
        cmd_rules(args)
    else:
        cmd_chat(args)


if __name__ == "__main__":
    main()
