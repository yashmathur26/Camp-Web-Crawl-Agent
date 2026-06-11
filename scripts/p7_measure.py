"""roadmap2 Phase 7: cut-over measurement.

Run Lexington + Burlington through the full roadmap2 pipeline (navigator_v2 +
name integrity + render + evidence filter + anti-fab + validation gate + dedupe)
on the correct instruct model, then report against data/_baseline_v2/:

  published       rows in camp_sessions.csv (post-gate)
  junk_rate       fraction of PUBLISHED rows still flagged by audit_row (target 0)
  fabricated      published rows with no evidence + chrome/empty name (target 0)
  parent_ready    published rows verified registrable (target: up vs baseline)
  quarantined     rows the gate diverted to the quarantine CSV

Exit code is non-zero if the quality gate fails (junk_rate>0 or fabricated>0).
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SETTINGS  # noqa: E402
from src.data_layout import camp_sessions_csv  # noqa: E402
from src.junk_audit import audit_row, is_unusable_name  # noqa: E402
from src.sessions import enumerate_town  # noqa: E402

TOWNS = ["Lexington", "Burlington"]
BASELINE_V2 = Path("data/_baseline_v2")
OUT = Path("data/_baseline_v2/p7_measure.json")


def _seed_urls(town: str) -> list[str]:
    base = json.loads((Path("data/_baseline") / town.lower() / "baseline.json").read_text())
    return [p["seed_url"] for p in base["providers"]]


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _baseline_parent_ready(town: str) -> int:
    rows = _read_csv(BASELINE_V2 / town.lower() / "camp_sessions.csv")
    return sum(1 for r in rows if r.get("parent_verdict") == "parent_ready")


async def _run_town(town: str) -> dict:
    await enumerate_town(town, urls=_seed_urls(town))
    published = _read_csv(camp_sessions_csv(town))
    quarantine = _read_csv(camp_sessions_csv(town).with_name("camp_sessions_quarantine.csv"))

    junk = [r for r in published if audit_row(r)]
    fabricated = [
        r for r in published if is_unusable_name(r.get("name", "")) and not any(
            (r.get(k) or "").strip() for k in ("ages", "dates", "price")
        )
    ]
    parent_ready = sum(1 for r in published if r.get("parent_verdict") == "parent_ready")
    base_published = len(_read_csv(BASELINE_V2 / town.lower() / "camp_sessions.csv"))

    return {
        "town": town,
        "baseline_published": base_published,
        "published": len(published),
        "junk_published": len(junk),
        "junk_rate": round(len(junk) / len(published), 3) if published else 0.0,
        "fabricated": len(fabricated),
        "parent_ready": parent_ready,
        "quarantined": len(quarantine),
    }


async def main() -> int:
    SETTINGS.update(
        {
            "b5_navigator_v2": True,
            "dry_run": False,
            "filter_to_focus": True,
        }
    )
    out = {"towns": []}
    gate_ok = True
    for town in TOWNS:
        print(f"=== {town}: roadmap2 full-pipeline run ===", flush=True)
        res = await _run_town(town)
        out["towns"].append(res)
        if res["junk_rate"] > 0 or res["fabricated"] > 0:
            gate_ok = False
        print(
            f"  {town}: published={res['published']} junk_rate={res['junk_rate']} "
            f"fabricated={res['fabricated']} parent_ready={res['parent_ready']} "
            f"quarantined={res['quarantined']}",
            flush=True,
        )

    out["gate_ok"] = gate_ok
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nWrote {OUT}\nGATE_OK={gate_ok}")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
