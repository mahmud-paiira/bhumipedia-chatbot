"""Live API server for the ভূমি আইন চ্যাটবট.

Serves answers computed from the live iLKMS PostgreSQL database, reusing the
exact same Q&A pipeline (build_db.extract_db) and scoring (scorer.py) as the
static build. The client (app.js) requests /api/search and falls back to the
bundled data.js when this server is unreachable.

Run:  python server.py  (reads DATABASE_URL from .env)
Endpoints:
  GET /api/health          -> {"ok": bool, "rows": {...}}
  GET /api/search?q=...&lang=bn  -> same shape as app.js findAnswer()
  GET /api/stats           -> dataset size + row counts
"""
import io
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dotenv

dotenv.load_dotenv()

HOST = os.environ.get("BHUMI_HOST", "127.0.0.1")
PORT = int(os.environ.get("BHUMI_PORT", "8790"))

_WS = re.compile(r"[ \t\u00a0]+")


def _clean(s):
    return _WS.sub(" ", str(s)).strip()


def _norm_key(s):
    s = str(s).lower()
    s = re.sub(r"[^\w\u0980-\u09FF]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_dataset(tables):
    """Same clean/dedup mapping as build_data.py, from a tables dict."""
    from build_db import extract_db

    rows, seen = [], set()
    for it in extract_db(tables):
        q = _clean(it["q"])
        a = _clean(it["a"])
        k = _norm_key(q)
        if len(k) < 2 or len(a) < 10 or k in seen:
            continue
        seen.add(k)
        ent = {"q": q, "a": a}
        if it.get("more"):
            ent["more"] = _clean(it["more"])
        if it.get("tpl"):
            ent["t"] = 1
        rows.append(ent)
    return rows


class State:
    def __init__(self):
        import db_source

        self.src = db_source._Conn()
        self.dataset = []
        self.row_counts = {}
        self.last_error = None

    def refresh(self):
        """Reload tables from the live DB and rebuild the dataset atomically."""
        import db_source
        from scorer import prepare_dataset

        if not self.src.conn:
            if not self.src.connect():
                self.last_error = "no_connection"
                return False
        tb = self.src.load()
        if tb is None:
            self.last_error = "load_failed"
            return False
        ds = build_dataset(tb)
        if not ds:
            self.last_error = "empty_dataset"
            return False
        count = {k[len("public."):]: len(v["rows"]) for k, v in tb.items()
                 if k.startswith("public.")}
        prepare_dataset(ds)
        self.dataset = ds
        self.row_counts = count
        self.last_error = None
        return True

    def search(self, q, lang="bn"):
        from scorer import find_answer

        r = find_answer(q, self.dataset, lang)
        r["offline"] = {"dataset": len(self.dataset), "rows": self.row_counts}
        return r


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):  # noqa: N802
            self._send(200, {"ok": True})

        def do_GET(self):  # noqa: N802
            try:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/api/health":
                    self._send(200, {
                        "ok": state.src.health(),
                        "dataset": len(state.dataset),
                        "rows": state.row_counts,
                        "error": state.last_error,
                    })
                    return
                if parsed.path == "/api/stats":
                    self._send(200, {
                        "dataset": len(state.dataset),
                        "rows": state.row_counts,
                        "error": state.last_error,
                    })
                    return
                if parsed.path == "/api/search":
                    qs = urllib.parse.parse_qs(parsed.query)
                    q = (qs.get("q") or [""])[0].strip()
                    if not q:
                        self._send(400, {"error": "missing 'q' param"})
                        return
                    lang = (qs.get("lang") or ["bn"])[0]
                    self._send(200, state.search(q, lang))
                    return
                self._send(404, {"error": "not found"})
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"error": str(exc)})

        def log_message(self, *a):  # quiet
            pass

    return Handler


def main():
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    state = State()
    if state.refresh():
        print(f"[server] live dataset ready: {len(state.dataset)} entries")
    else:
        print(f"[server] WARNING: live DB unavailable ({state.last_error}); "
              "client will use offline data.js", file=sys.stderr)
    httpd = ThreadingHTTPServer((HOST, PORT), make_handler(state))
    print(f"[server] listening on http://{HOST}:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        state.src.close()


if __name__ == "__main__":
    main()