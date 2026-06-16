"""Part C Stage 5 — multi-town orchestration with budgets and resume.

`python -m src.run --no-dry-run --phase C --all-towns [--resume]`
`python -m src.run --no-dry-run --phase C --towns Lexington,Arlington`

- Towns ordered by population descending (big towns seed the provider registry,
  maximizing Stage-4 savings for the rest).
- Checkpoint: cache/part_c_progress.json (resume after interrupt).
- Per-town search budget: SETTINGS["gap_search_budget_per_town"] (replaces the
  global truncation for Part C runs).
- Spend log: data/shared/part_c_cost_ledger.csv.
"""

from __future__ import annotations

import csv
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from config.settings import SETTINGS
from config.town_geo import TOWN_GEO, towns_by_population
from src.agentic_gap import run_agentic_gap
from src.parent_verify import load_sessions_for_verify

logger = logging.getLogger(__name__)

from src.data_layout import DATA_ROOT as _DATA_ROOT

# Resume checkpoint stays in the shared cache/ (cross-run resume); the cost
# ledger follows DATA_ROOT so a per-run workspace keeps its own ledger.
PROGRESS_PATH = Path("cache/part_c_progress.json")
LEDGER_PATH = _DATA_ROOT / "shared" / "part_c_cost_ledger.csv"


def _load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_progress(progress: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_PATH.write_text(json.dumps(progress, indent=1))


def _log_spend(town: str, result: dict, seconds: float) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not LEDGER_PATH.exists()
    cost = result.get("total_searches", 0) * float(SETTINGS.get("cost_per_query_usd", 0.001))
    with open(LEDGER_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "town", "searches", "est_cost_usd", "new_sessions",
                        "core_pct", "wall_clock_s"])
        w.writerow([
            datetime.now(timezone.utc).isoformat(timespec="seconds"), town,
            result.get("total_searches", 0), round(cost, 4),
            result.get("new_sessions", 0),
            (result.get("coverage") or {}).get("core_pct", ""),
            round(seconds, 1),
        ])


def run_part_c(
    *,
    towns: list[str] | None = None,
    all_towns: bool = False,
    resume: bool = True,
    rounds: int | None = None,
) -> dict:
    """Loop gap fill per town with checkpointing. Returns the progress dict."""
    if all_towns:
        town_list = towns_by_population()
    elif towns:
        town_list = [t for t in towns if t in TOWN_GEO] or towns
    else:
        raise ValueError("run_part_c needs towns=[...] or all_towns=True")

    budget = int(SETTINGS.get("gap_search_budget_per_town", 400))
    rounds = rounds or int(SETTINGS.get("gap_rounds_default", 2))
    progress = _load_progress() if resume else {}

    for town in town_list:
        state = progress.get(town, {})
        if state.get("status") == "done":
            logger.info("Part C: %s already done (resume) — skipping", town)
            continue
        from src.engine_bridge import engine_sessions_for_town

        sessions = engine_sessions_for_town(town) or load_sessions_for_verify(town)
        if not sessions:
            logger.info("Part C: %s has no enumerated sessions yet — recording skip "
                        "(run phases A-P first)", town)
            progress[town] = {"status": "no_catalog",
                              "ts": datetime.now(timezone.utc).isoformat()}
            _save_progress(progress)
            continue
        logger.info("Part C: %s — %d sessions in catalog, budget %d searches",
                    town, len(sessions), budget)
        t0 = time.monotonic()
        try:
            result = run_agentic_gap(
                town, rounds=rounds, max_searches=budget, sessions=sessions,
            )
        except Exception as exc:  # noqa: BLE001 — one town must not kill the county
            logger.exception("Part C failed for %s: %s", town, exc)
            progress[town] = {"status": "error", "error": str(exc)[:300],
                              "ts": datetime.now(timezone.utc).isoformat()}
            _save_progress(progress)
            continue
        seconds = time.monotonic() - t0
        _log_spend(town, result, seconds)
        progress[town] = {
            "status": "done",
            "ts": datetime.now(timezone.utc).isoformat(),
            "searches": result.get("total_searches", 0),
            "new_sessions": result.get("new_sessions", 0),
            "coverage": result.get("coverage", {}),
            "wall_clock_s": round(seconds, 1),
        }
        _save_progress(progress)
    return progress
