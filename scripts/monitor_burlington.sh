#!/usr/bin/env bash
# Monitor the detached Burlington pipeline run.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/logs/shared/burlington.pid"
LOG="$ROOT/logs/shared/burlington_run.log"

PY_PID=""
if pgrep -f "src.run.*--town Burlington" >/dev/null 2>&1; then
  PY_PID="$(pgrep -f "src.run.*--town Burlington" | head -1)"
  echo "Python running (PID $PY_PID)"
  ps -p "$PY_PID" -o etime,pcpu,state 2>/dev/null
elif [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if ps -p "$PID" > /dev/null 2>&1; then
    echo "Wrapper running (PID $PID) — waiting for Python child"
    ps -p "$PID" -o etime,pcpu,state 2>/dev/null
  else
    echo "Not running (stale PID $PID in $PID_FILE)"
  fi
else
  echo "Not running (no PID file, no Burlington src.run process)"
fi

echo ""
if [[ -f "$LOG" ]]; then
  LOG_AGE=$(( $(date +%s) - $(stat -f %m "$LOG" 2>/dev/null || echo 0) ))
  echo "Log: $LOG (last write ${LOG_AGE}s ago)"
  if (( LOG_AGE > 120 )); then
    echo "WARNING: log silent >2 min — may be stuck on LLM classify or dead"
  elif (( LOG_AGE > 30 )); then
    echo "Note: quiet period is normal during LLM classify (up to ~2 min)"
  fi
else
  echo "Log: (not found)"
fi

echo "--- last 15 lines ---"
tail -15 "$LOG" 2>/dev/null || echo "(no log yet)"

echo ""
if [[ -f "$ROOT/data/shared/phase_a/candidates.csv" ]]; then
  python3 - "$ROOT" <<'PY'
import csv, sys
root = sys.argv[1]
rows = list(csv.DictReader(open(f"{root}/data/shared/phase_a/candidates.csv")))
pref = [r for r in rows if r.get("town") == "Burlington" and r.get("preferred") == "true"]
done = sum(1 for r in pref if r.get("crawled") == "true")
print(f"Phase B progress: {done}/{len(pref)} preferred sources crawled")
PY
fi

LINKS="$ROOT/data/shared/phase_b/camp_links.csv"
if [[ -f "$LINKS" ]]; then
  echo "camp_links.csv: $(wc -l < "$LINKS") lines"
fi
