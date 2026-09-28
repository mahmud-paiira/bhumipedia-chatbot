#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Refresh the datasets from the live API, safe to run as a background job.

    python update_datasets.py                 # refresh live Q&A + rebuild data.js + prune docs.js
    python update_datasets.py --no-refresh    # rebuild from the disk caches only
    python update_datasets.py --portal        # also refresh the Bhumipedia portal cache
    python update_datasets.py --docs          # also rebuild docs.js (downloads act PDFs)
    python update_datasets.py --no-verify     # skip the node test suites
    python update_datasets.py --quiet         # machine-friendly output

Designed for periodic execution (cron / systemd timer / Task Scheduler). Each
run:

  1. refetches /api/v1/qna/type1/ and /type2/ (and optionally the portal), so
     questions and answers that appeared since the last run land automatically
  2. rebuilds data.js = every source through qa_dedup (same pipeline as
     server.py, so file and API cannot disagree)
  3. verifies with test.js and test_samples.js --tolerant (a SUGGEST-tier query
     that now gains a real answer counts as an improvement, not a failure)
  4. deploys only if verification passes AND the dataset did not shrink by more
     than 5% (a broken upstream fetch must not shrink the live corpus)
  5. rolls back to data.js.bak on any failure, so the serving dataset is never
     left broken
  6. writes dataset_update.json (machine-readable status for monitoring) and a
     human log line, including how long each stage ran

Exit codes: 0 = deployed, 1 = rolled back / failed, 2 = usage error.
"""
import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_JS = os.path.join(HERE, "data.js")
BAK_JS = os.path.join(HERE, "data.js.bak")
STATUS_JSON = os.path.join(HERE, "dataset_update.json")
MIN_KEEP = 0.95  # refuse to deploy if the new dataset shrinks below this fraction


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _warn(msg, status):
    print(f"[update {_now()}] WARN {msg}")
    status.setdefault("warnings", []).append(msg)


def _count_dataset(path=DATA_JS):
    try:
        with open(path, encoding="utf-8") as f:
            body = f.read()
        return len(json.loads(body[body.index("["):body.rindex("]") + 1]))
    except Exception:  # noqa: BLE001  (a missing/corrupt file is not fatal)
        return None


def _captured_build(refresh, portal):
    """Refresh caches (if asked) and rebuild rows, capturing source output.

    Returns (rows_or_None, log_tail). Sources degrade gracefully on network
    failure (they fall back to their disk caches), so a bad fetch never aborts
    the run by itself.
    """
    buf = io.StringIO()
    real, sys.stdout = sys.stdout, buf
    try:
        if refresh:
            import api_source
            api_source.extract_api_entries(refresh=True)  # fetch + update cache
            if portal:
                import bhumipedia_source
                bhumipedia_source.fetch(force=True)
        from build_data import rows_from_sources
        rows = rows_from_sources()
        return rows, buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        return None, buf.getvalue() + f"\n[build] FAILED: {exc}\n"
    finally:
        sys.stdout = real


def _run(cmd):
    """Run a command, return (ok, tail_output)."""
    try:
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=3600)
        tail = (proc.stdout or "").strip().splitlines()
        return proc.returncode == 0, "\n".join(tail[-25:])
    except FileNotFoundError:
        return None, ""
    except subprocess.TimeoutExpired:
        return False, "timed out after 3600s"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--refresh", dest="refresh", action="store_true", default=True,
                   help="refetch from the live API (default)")
    p.add_argument("--no-refresh", dest="refresh", action="store_false",
                   help="rebuild from the disk caches only")
    p.add_argument("--portal", action="store_true",
                   help="also refresh the portal cache (bhumipedia_source)")
    p.add_argument("--docs", action="store_true",
                   help="also rebuild docs.js (downloads act PDFs)")
    p.add_argument("--verify", dest="verify", action="store_true", default=True,
                   help="run node test suites (default)")
    p.add_argument("--no-verify", dest="verify", action="store_false",
                   help="skip node test suites")
    p.add_argument("--quiet", action="store_true",
                   help="one line per stage, suitable for cron")
    args = p.parse_args()

    status = {
        "script": os.path.basename(__file__),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "refresh": args.refresh,
        "portal": args.portal,
        "docs": args.docs,
        "ok": False,
        "exit": 1,
    }
    stages = []

    def stage(name, dur):
        stages.append({"step": name, "duration_s": round(dur, 1)})
        status["stages"] = stages
        if args.quiet:
            print(f"[update] {name}: {dur:.1f}s")
        else:
            print(f"[update {_now()}] {name}: {dur:.1f}s")

    t = time.perf_counter()
    prev = _count_dataset()
    if prev is None:
        _warn(f"cannot read current {os.path.basename(DATA_JS)} size", status)

    rows, log_tail = _captured_build(args.refresh, args.portal)
    build_s = time.perf_counter() - t
    if rows is None or not rows:
        status["error"] = "build produced no rows; keeping existing dataset"
        print(f"[update {_now()}] ERROR {status['error']}", file=sys.stderr)
        return _finish(status, 1)
    status["build_log_tail"] = log_tail.strip().splitlines()[-35:]
    stage(f"build ({len(rows)} rows)", build_s)

    delta = (len(rows) - prev) if prev is not None else 0
    status["dataset_prev"] = prev
    status["dataset_new"] = len(rows)
    status["dataset_delta"] = delta
    if prev is not None and len(rows) < prev * MIN_KEEP:
        status["error"] = (f"dataset shrank {100 * (1 - len(rows) / prev):.1f}% "
                           f"({prev} -> {len(rows)}); refusing to deploy")
        print(f"[update {_now()}] ERROR {status['error']}", file=sys.stderr)
        return _finish(status, 1)

    # ---- stage 2: deploy (backup, write atomically, roll back on failure) ----
    import build_data
    if os.path.exists(BAK_JS):
        os.remove(BAK_JS)
    if os.path.exists(DATA_JS):
        os.replace(DATA_JS, BAK_JS)  # keep the currently-served dataset as backup
    t = time.perf_counter()
    build_data.write_dataset(rows)          # atomic os.replace underneath
    stage("deploy data.js", time.perf_counter() - t)

    # ---- stage 3: verification ----
    tests = {}
    ok = True
    if args.verify:
        if shutil.which("node") is None:
            _warn("node not found; skipping verification (dataset kept)", status)
        else:
            for name, cmd in (("test.js", ["node", "test.js"]),
                               ("test_samples.js", ["node", "test_samples.js", "--tolerant"])):
                t = time.perf_counter()
                good, tail = _run(cmd)
                stage(f"verify {name} ({'pass' if good else 'FAIL'})",
                      time.perf_counter() - t)
                tests[name] = {"ok": bool(good), "tail": tail}
                if good is False:
                    ok = False
            if ok:
                t = time.perf_counter()
                _run(["node", "smoke_act.js"])  # informational only
                stage("smoke_act.js", time.perf_counter() - t)
    status["tests"] = tests

    # ---- stage 4: docs (optional, never rolls back data.js) ----
    if args.docs:
        t = time.perf_counter()
        good, tail = _run([sys.executable, "build_docs.py"])
        status["docs"] = {"ok": bool(good), "tail": tail}
        stage(f"docs.js ({'pass' if good else 'FAIL'})",
              time.perf_counter() - t)
        if good is False:
            _warn("docs.js rebuild failed; data.js is unaffected", status)

    if not ok:
        try:
            os.replace(BAK_JS, DATA_JS)  # restore the previously-served dataset
        except OSError as exc:
            _warn(f"could not restore {os.path.basename(BAK_JS)}: {exc}", status)
        status["error"] = (f"verification failed; rolled back to "
                           f"{os.path.basename(BAK_JS)}")
        print(f"[update {_now()}] ERROR {status['error']}", file=sys.stderr)
        for name, t in tests.items():
            if t.get("ok") is False:
                print(f"[update {_now()}]   {name} failed:\n{t['tail']}",
                      file=sys.stderr)
        return _finish(status, 1)

    status["ok"] = True
    status["exit"] = 0
    print(f"[update {_now()}] OK deployed dataset {status['dataset_new']} "
          f"({'+' if delta >= 0 else ''}{delta})")
    return _finish(status, 0)


def _finish(status, code):
    status["finished_at"] = datetime.now().isoformat(timespec="seconds")
    status["exit"] = code
    tmp = STATUS_JSON + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, STATUS_JSON)
    return code


if __name__ == "__main__":
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace")
    sys.exit(main())