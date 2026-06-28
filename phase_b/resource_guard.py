"""Global memory gate + RSS trace (W3W crash P0.3).

A heavy phase (Phase C gap-fill, engine run, Phase B crawl) checks free memory
before starting and raises MemoryBudgetError if the machine can't afford it —
so the orchestrator skips/defers and writes a partial summary instead of
letting Jetsam kill the process mid-run.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class MemoryBudgetError(RuntimeError):
    """Raised when free memory is below the threshold a phase requires."""


def available_memory_mb() -> int:
    try:
        import psutil

        return int(psutil.virtual_memory().available / (1024 ** 2))
    except Exception:  # noqa: BLE001 — without psutil, don't block (return large)
        return 1 << 30


def process_rss_mb() -> int:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss / (1024 ** 2))
    except Exception:  # noqa: BLE001
        return 0


def require_memory(min_mb: int, phase: str) -> None:
    """Raise MemoryBudgetError if free memory is below min_mb."""
    free = available_memory_mb()
    if free < min_mb:
        raise MemoryBudgetError(
            f"Skipping {phase}: only {free}MB free, need {min_mb}MB "
            f"(close apps or set FIREFLY_RESOURCE_PROFILE=16gb)"
        )
    logger.info("memory gate ok for %s: %dMB free (need %dMB)", phase, free, min_mb)


def min_free_for(phase: str) -> int:
    """Per-phase threshold from the active resource profile."""
    from config.settings import SETTINGS

    return int(SETTINGS.get(
        {
            "phase_c": "min_free_mb_phase_c",
            "engine": "min_free_mb_engine",
            "crawl": "min_free_mb_crawl",
        }.get(phase, "min_free_mb_engine"),
        1500,
    ))


def gate(phase: str) -> None:
    """Convenience: gate a named phase against its profile threshold."""
    require_memory(min_free_for(phase), phase)


def trace_path() -> Path:
    root = os.environ.get("FIREFLY_LOGS_ROOT") or "logs"
    return Path(root) / "memory_trace.jsonl"


def log_memory(phase: str, **extra) -> None:
    """Append an RSS/free-memory sample to the trace (P2.1)."""
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "phase": phase,
        "rss_mb": process_rss_mb(),
        "free_mb": available_memory_mb(),
        **extra,
    }
    try:
        p = trace_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001 — tracing must never break a run
        pass
    logger.info("mem[%s] rss=%dMB free=%dMB", phase, rec["rss_mb"], rec["free_mb"])
