#!/usr/bin/env bash
# After Phase B completes, run B.5 → Q → P → trail → gap for Burlington.
#   bash scripts/run_burlington_finish.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG="$ROOT/logs/shared/burlington_finish.log"

nohup "$ROOT/venv/bin/python" -m src.run \
  --no-dry-run \
  --phase all \
  --town Burlington \
  --preferred-only \
  --log-file "$LOG" \
  </dev/null >/dev/null 2>&1 &

echo $! > "$ROOT/logs/shared/burlington_finish.pid"
echo "Started post-B phases (PID $!)"
echo "Log: $LOG"
