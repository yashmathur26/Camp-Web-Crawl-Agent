"""P5.1: re-run baseline towns with b5_navigator_v2=true and diff vs data/_baseline/.

Reproduces each town's provider set from its committed baseline.json seed URLs,
runs the navigator-v2 path, and reports per-provider session-count deltas plus
the parent_ready count. Exit code is non-zero if any provider regresses (loses
sessions vs baseline) so the cutover gate can key off it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SETTINGS  # noqa: E402
from src.sessions import enumerate_town, host_of  # noqa: E402

TOWNS = ["Lexington", "Burlington"]
BASELINE_ROOT = Path("data/_baseline")
OUT = Path("data/_baseline/_p5_navigator_v2_compare.json")


def _load_baseline(town: str) -> dict:
    slug = town.lower()
    payload = json.loads((BASELINE_ROOT / slug / "baseline.json").read_text())
    by_host = {}
    for p in payload["providers"]:
        by_host[p["host"]] = {
            "seed_url": p["seed_url"],
            "session_count": p["session_count"],
        }
    return {"payload": payload, "by_host": by_host}


def _parent_ready(sessions: list[dict]) -> int:
    return sum(1 for s in sessions if s.get("parent_verdict") == "parent_ready")


async def _run_town(town: str) -> dict:
    base = _load_baseline(town)
    seed_urls = [p["seed_url"] for p in base["payload"]["providers"]]
    results = await enumerate_town(town, urls=seed_urls)

    rows = []
    regressions = []
    new_total = 0
    base_total = 0
    pr_total = 0
    for res in results:
        host = host_of(res.get("url", ""))
        sessions = res.get("sessions") or []
        new_count = len(sessions)
        pr = _parent_ready(sessions)
        base_count = base["by_host"].get(host, {}).get("session_count", 0)
        new_total += new_count
        base_total += base_count
        pr_total += pr
        row = {
            "host": host,
            "platform": res.get("platform", ""),
            "baseline_sessions": base_count,
            "new_sessions": new_count,
            "parent_ready": pr,
            "delta": new_count - base_count,
        }
        rows.append(row)
        if new_count < base_count:
            regressions.append(row)

    return {
        "town": town,
        "baseline_total": base_total,
        "new_total": new_total,
        "parent_ready_total": pr_total,
        "providers": rows,
        "regressions": regressions,
    }


async def main() -> int:
    SETTINGS["b5_navigator_v2"] = True
    SETTINGS["dry_run"] = False
    out = {"towns": []}
    any_regression = False
    for town in TOWNS:
        print(f"=== {town}: running navigator-v2 enumeration ===", flush=True)
        town_res = await _run_town(town)
        out["towns"].append(town_res)
        any_regression = any_regression or bool(town_res["regressions"])
        print(
            f"  {town}: baseline={town_res['baseline_total']} "
            f"new={town_res['new_total']} parent_ready={town_res['parent_ready_total']} "
            f"regressions={len(town_res['regressions'])}",
            flush=True,
        )

    out["any_regression"] = any_regression
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nWrote {OUT}")
    print(f"ANY_REGRESSION={any_regression}")
    return 1 if any_regression else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
