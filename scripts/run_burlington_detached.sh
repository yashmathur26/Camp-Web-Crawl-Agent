#!/usr/bin/env bash
# Detached Burlington Phase B harvest (resume-safe). Run from Terminal.app:
#   bash scripts/run_burlington_detached.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_FILE="$ROOT/logs/shared/burlington.pid"
LOG="$ROOT/logs/shared/burlington_run.log"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if ps -p "$OLD_PID" > /dev/null 2>&1; then
    echo "Already running (PID $OLD_PID). Stop it first or delete $PID_FILE"
    exit 1
  fi
fi

pkill -f "src.run.*Burlington" 2>/dev/null || true
sleep 1

nohup "$ROOT/venv/bin/python" -m src.run \
  --no-dry-run \
  --phase B \
  --town Burlington \
  --preferred-only \
  --log-file "$LOG" \
  </dev/null >/dev/null 2>&1 &

echo $! > "$PID_FILE"
echo "Started Phase B (PID $(cat "$PID_FILE"))"
echo "Log: $LOG"
echo "Monitor: bash scripts/monitor_burlington.sh"
