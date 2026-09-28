"""Live API server for the ভূমি আইন চ্যাটবট.

Serves answers computed from the live iLKMS PostgreSQL database, reusing the
exact same Q&A pipeline (build_db.extract_db) and scoring (scorer.py) as the
static build. The client (app.js) requests /api/search and falls back to the
bundled data.js when this server is unreachable.

It also serves the public read-only dataset APIs from public_api.py, which
mirror the live bhumipedia.land.gov.bd contract:
  /api/ebooks/full/, /api/blogs/full/, /api/forums/full/
  /api/v1/qna/type1/[/<id>], /api/v1/qna/type2/[/<id>]

Run:
  python server.py            # live PostgreSQL (DATABASE_URL from .env)
  python server.py --sql      # bundled .sql snapshot, no database needed
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

import public_api

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
    """Same clean/dedup mapping as data.js, from a tables dict.

    Delegates to qa_dedup so the public API and data.js can never disagree.
    """
    from build_db import extract_db
    from qa_dedup import clean_rows, load_curated

    return clean_rows(extract_db(tables), load_curated())


class State:
    def __init__(self, use_sql=False, sql_path=None):
        import db_source

        self.use_sql = use_sql
        self.sql_path = sql_path
        self.src = None if use_sql else db_source._Conn()
        self.tables = None
        self.dataset = []
        self.row_counts = {}
        self.full = {"acts": [], "blogs": [], "forums": []}
        self.qna = {"type1": [], "type2": []}
        self.last_error = None

    def _load_tables(self):
        if self.use_sql:
            from build_db import load_tables_from_sql

            return load_tables_from_sql(self.sql_path)
        if not self.src.conn:
            if not self.src.connect():
                self.last_error = "no_connection"
                return None
        return self.src.load()

    def _build_full(self):
        """Pre-build the public dataset payloads.

        They are plain arrays with no query parameters, so they are rendered
        once per reload instead of per request. The rows are json.dumps'd
        because they never change between reloads.
        """
        t = self.tables
        self.full = {
            "acts": json.dumps(public_api.build_full_acts(t), ensure_ascii=False),
            "blogs": json.dumps(public_api.build_full_blogs(t), ensure_ascii=False),
            "forums": json.dumps(public_api.build_full_forums(t), ensure_ascii=False),
        }
        rows = public_api.build_qna_rows(self.dataset)
        self.qna = {
            "type2": json.dumps(rows, ensure_ascii=False),
            "type1": json.dumps(public_api.qna_type1(rows), ensure_ascii=False),
        }
        self.qna_rows = {"type1": public_api.qna_type1(rows), "type2": rows}

    def refresh(self):
        """Reload tables and rebuild the dataset plus public payloads atomically."""
        from scorer import prepare_dataset

        tb = self._load_tables()
        if tb is None:
            if self.last_error is None:
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
        self.tables = tb
        self.last_error = None
        self._build_full()
        return True

    def search(self, q, lang="bn"):
        from scorer import find_answer

        r = find_answer(q, self.dataset, lang)
        r["offline"] = {"dataset": len(self.dataset), "rows": self.row_counts}
        return r

    def healthy(self):
        return True if self.use_sql else self.src.health()


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _base_url(self):
            host = self.headers.get("Host") or "%s:%d" % (HOST, PORT)
            proto = self.headers.get("X-Forwarded-Proto") or "http"
            return "%s://%s" % (proto, host)

        def _serve_full(self, kind):
            """The three pre-rendered full-collection endpoints."""
            payload = state.full.get(kind)
            if payload is None:
                self._send(404, {"error": "not found"})
            else:
                self._send(200, payload.encode("utf-8"))

        def _serve_qna(self, kind, qs, rest):
            """List, detail, and DRF-style pagination for the two qna endpoints."""
            if kind not in state.qna:
                self._send(404, {"error": "not found"})
                return
            path = "/api/v1/qna/%s/" % kind
            rows = state.qna_rows[kind]
            if rest:
                try:
                    want = int(rest)
                except ValueError:
                    self._send(404, {"detail": "Not found."})
                    return
                for r in rows:
                    if r["id"] == want:
                        self._send(200, r)
                        return
                self._send(404, {"detail": "Not found."})
                return
            paged = public_api.paginate(rows, qs, self._base_url(), path)
            if isinstance(paged, list):
                self._send(200, state.qna[kind].encode("utf-8"))
            else:
                self._send(200, paged)

        def do_OPTIONS(self):  # noqa: N802
            self._send(200, {"ok": True})

        def do_GET(self):  # noqa: N802
            try:
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                qs = urllib.parse.parse_qs(parsed.query)

                if path == "/api/health":
                    self._send(200, {
                        "ok": state.healthy(),
                        "source": "sql" if state.use_sql else "postgres",
                        "dataset": len(state.dataset),
                        "rows": state.row_counts,
                        "full": {k: len(json.loads(v)) for k, v in state.full.items()},
                        "qna": {k: len(v) for k, v in state.qna_rows.items()},
                        "error": state.last_error,
                    })
                    return
                if path == "/api/stats":
                    self._send(200, {
                        "dataset": len(state.dataset),
                        "rows": state.row_counts,
                        "error": state.last_error,
                    })
                    return
                if path == "/api/search":
                    q = (qs.get("q") or [""])[0].strip()
                    if not q:
                        self._send(400, {"error": "missing 'q' param"})
                        return
                    lang = (qs.get("lang") or ["bn"])[0]
                    self._send(200, state.search(q, lang))
                    return

                # --- public read-only dataset APIs -------------------------
                if path in ("/api/ebooks/full/", "/api/ebooks/full"):
                    self._serve_full("acts"); return
                if path in ("/api/blogs/full/", "/api/blogs/full"):
                    self._serve_full("blogs"); return
                if path in ("/api/forums/full/", "/api/forums/full"):
                    self._serve_full("forums"); return

                m = re.match(r"^/api/v1/qna/(type1|type2)/([^/]+)?/?$", path)
                if m:
                    self._serve_qna(m.group(1), qs, m.group(2)); return

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

    argv = sys.argv[1:]
    use_sql = "--sql" in argv
    sql_path = None
    for i, a in enumerate(argv):
        if a == "--sql-path" and i + 1 < len(argv):
            sql_path = argv[i + 1]
    host = os.environ.get("BHUMI_HOST", "127.0.0.1")
    port = int(os.environ.get("BHUMI_PORT", "8790"))

    state = State(use_sql=use_sql, sql_path=sql_path)
    if state.refresh():
        print(f"[server] live dataset ready: {len(state.dataset)} entries")
        print("[server] public APIs: acts={0} blogs={1} forums={2} | qna type1={3} type2={4}".format(
            len(json.loads(state.full["acts"])), len(json.loads(state.full["blogs"])),
            len(json.loads(state.full["forums"])), len(state.qna_rows["type1"]),
            len(state.qna_rows["type2"])))
    else:
        print(f"[server] WARNING: source unavailable ({state.last_error}); "
              "client will use offline data.js", file=sys.stderr)
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    print(f"[server] listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if state.src is not None:
            state.src.close()


if __name__ == "__main__":
    main()