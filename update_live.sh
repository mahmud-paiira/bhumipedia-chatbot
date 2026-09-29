#!/usr/bin/env bash
# update_live.sh - refresh the Bhumipedia datasets on a schedule or on demand.
#   --cron     : quiet run for cron/systemd (00:00). Log to logs/update-*.log.
#   --manual   : live progress on the terminal, then a summary of the update.
#   (no TTY)   : behaves like --cron.
#   --install  : add a 00:00 crontab entry for the current user.
#   --no-refresh / --portal / --docs : passed through to update_datasets.py
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PYTHON_CMD="${PYTHON:-python3}"
LOG_DIR="${LOG_DIR:-logs}"
CRON_SCHED="${CRON_SCHED:-0 0 * * *}"
KEEP_LOGS="${KEEP_LOGS:-3}"
EXTRA=()

MODE="auto"
if [[ ! -t 1 ]]; then
  MODE="cron"
fi

for a in "$@"; do
  case "$a" in
    --cron)       MODE="cron" ;;
    --manual)     MODE="manual" ;;
    --install)    MODE="install" ;;
    --no-refresh) EXTRA+=("--no-refresh") ;;
    --portal)     EXTRA+=("--portal") ;;
    --docs)       EXTRA+=("--docs") ;;
    -h|--help)
      cat <<'EOF'
usage: update_live.sh [--cron | --manual] [--no-refresh] [--portal] [--docs]
       update_live.sh --install

  --cron       quiet run for cron/systemd; right after midnight. Appends one
               line to logs/cron.log and full output to logs/update-*.log.
  --manual     live progress on the terminal, then a summary of the update.
  --install    install a "0 0 * * *" crontab entry (override with CRON_SCHED).
  --no-refresh rebuild from disk caches only (offline).
  --portal     also refresh the Bhumipedia portal cache.
  --docs       also rebuild docs.js (downloads act PDFs).

Env: PYTHON=... (default python3), LOG_DIR=logs, CRON_SCHED='0 0 * * *',
     KEEP_LOGS=3 (update-*.log files kept after each --cron run).
Exit codes: 0 deployed, 1 rolled back/failed, 2 usage.
EOF
      exit 0 ;;
    *)
      echo "unknown option: $a" >&2
      exit 2 ;;
  esac
done

render_summary() {
  "$PYTHON_CMD" - <<'PY'
import json, sys
try:
    with open("dataset_update.json", encoding="utf-8") as f:
        s = json.load(f)
except FileNotFoundError:
    print("no dataset_update.json - nothing has been run yet")
    sys.exit(0)
print("=" * 58)
print("update report  %s -> %s" % (s.get("started_at"), s.get("finished_at")))
print("dataset        %s rows -> %s rows (%+d)" %
      (s.get("dataset_prev"), s.get("dataset_new"), s.get("dataset_delta")))
print("result         %s (exit %s)" % ("OK" if s.get("ok") else "FAILED", s.get("exit")))
for st in s.get("stages", []):
    print("  %-38s %6.1fs" % (st["step"], st["duration_s"]))
for name, t in (s.get("tests") or {}).items():
    print("  %-38s %s" % (name, "PASS" if t.get("ok") else "FAIL"))
for w in s.get("warnings", []):
    print("  WARN  %s" % w)
if s.get("error"):
    print("  ERROR %s" % s["error"])
print("=" * 58)
PY
}

if [[ "$MODE" == "install" ]]; then
  LINE="$CRON_SCHED cd '$HERE' && ./update_live.sh --cron"
  if crontab -l 2>/dev/null | grep -qF "./update_live.sh --cron"; then
    echo "already installed in crontab"
  else
    ( crontab -l 2>/dev/null; printf '%s\n' "$LINE" ) | crontab -
    echo "installed: $LINE"
  fi
  exit 0
fi

if [[ "$MODE" == "cron" ]]; then
  mkdir -p "$LOG_DIR"
  STAMP="$(date +%Y%m%d_%H%M%S)"
  OUT="$LOG_DIR/update-$STAMP.log"
  rc=0
  "$PYTHON_CMD" update_datasets.py --quiet "${EXTRA[@]}" >>"$OUT" 2>&1 || rc=$?
  render_summary >>"$OUT" 2>&1
  echo "[$(date '+%F %T')] update_live rc=$rc log=$OUT" >>"$LOG_DIR/cron.log"
  # keep only the newest $KEEP_LOGS run logs
  ls -1t "$LOG_DIR"/update-*.log 2>/dev/null | tail -n +"$((KEEP_LOGS + 1))" | xargs -r rm -f || true
  echo "run finished: rc=$rc  full log: $OUT"
  exit "$rc"
fi

"$PYTHON_CMD" update_datasets.py "${EXTRA[@]}"
rc=$?
echo
render_summary
exit "$rc"