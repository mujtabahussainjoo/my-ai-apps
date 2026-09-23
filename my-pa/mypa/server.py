"""myPA web server — stdlib http.server, serves web/ + /api/chat + /api/config."""
from __future__ import annotations
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB_DIR), **kw)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        from .config import load
        from .providers import chat
        u = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        if u == "/api/chat":
            cfg = load()
            msgs = data.get("messages", [])
            try:
                reply = chat(cfg, msgs)
            except Exception as e:
                reply = f"[error] {e}"
            return self._json({"reply": reply, "model": cfg.get("default_model")})
        if u == "/api/config":
            from .config import save_global
            cfg = load()
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k] = {**cfg[k], **v}
                else:
                    cfg[k] = v  # lists (incl. permissions) are replaced wholesale
            p = save_global(cfg)
            return self._json({"ok": True, "saved": str(p)})
        if u == "/api/rules":
            from . import rules as R
            op = data.get("op", "list")
            if op == "add":
                return self._json({"permissions": R.add_rule(
                    data["action"], data["resource"], data["effect"])})
            if op == "remove":
                return self._json({"permissions": R.remove_rule(int(data["index"]))})
            if op == "clear":
                return self._json({"permissions": R.clear_rules()})
            return self._json({"permissions": R.list_rules()})
        return self._json({"error": "unknown endpoint"}, 404)

    def do_GET(self):
        from .config import load
        if urlparse(self.path).path == "/api/config":
            return self._json(load())
        if urlparse(self.path).path == "/api/rules":
            from . import rules as R
            return self._json({"permissions": R.list_rules()})
        return super().do_GET()


def serve(port=3210):
    print(f"myPA web at http://127.0.0.1:{port}  (dir={WEB_DIR})")
    print("Open settings at /settings.html")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
