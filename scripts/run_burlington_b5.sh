#!/usr/bin/env bash
# Detached Burlington Phase B.5 (one provider at a time, incremental CSV writes).
# Run from Terminal.app for best stability:
#   bash scripts/run_burlington_b5.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PID_FILE="$ROOT/logs/shared/burlington_b5.pid"
LOG="$ROOT/logs/shared/burlington_b5_$(date +%Y%m%d_%H%M).log"

pkill -f "src.run.*--phase B5.*Burlington" 2>/dev/null || true
sleep 1

# os.setsid() detaches from Cursor/nohup parent so SIGHUP does not kill Playwright.
# PLAYWRIGHT_BROWSERS_PATH=0 → use browsers in venv (run once: python -m playwright install chromium)
export PYTHONUNBUFFERED=1
export PLAYWRIGHT_BROWSERS_PATH=0
nohup "$ROOT/venv/bin/python" -u -c "
import os, sys
os.setsid()
os.chdir(sys.argv[1])
os.execv(sys.argv[2], [sys.argv[2], '-m', 'src.run', '--no-dry-run', '--phase', 'B5', '--town', 'Burlington', '--preferred-only'])
" "$ROOT" "$ROOT/venv/bin/python" >>"$LOG" 2>&1 < /dev/null &
echo $! > "$PID_FILE"

echo "Started Phase B.5 (PID $(cat "$PID_FILE"))"
echo "Log: $LOG"
echo "Sessions CSV: data/burlington/phase_b5/ (updates after each provider)"
echo "Monitor: tail -f $LOG"
echo "Session detail: tail -f logs/burlington/b5_sessions_*.log"
