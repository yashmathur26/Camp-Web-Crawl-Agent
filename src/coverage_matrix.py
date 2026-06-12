"""Part C Stage 3.1 — the coverage matrix (operationalizes the guarantee).

Per town:   data/<town>/phase_gap/coverage_matrix.csv
County-wide: data/shared/coverage_county.csv — towns × categories, the master
"can a parent find it?" grid (the KPI artifact).

Statuses: covered | hole | exhausted | covered_via:<town> | nearest_town:<town>
"""

from __future__ import annotations

import csv
from pathlib import Path

from config.gap_taxonomy import ALL_CATEGORIES, CORE_CATEGORIES, GAP_CATEGORIES
from src.categorizer import categorize_sessions, coverage_by_category
from src.data_layout import town_phase_dir

SHARED_DIR = Path("data/shared")
COUNTY_CSV = SHARED_DIR / "coverage_county.csv"

MATRIX_COLUMNS = [
    "category", "tier", "parent_ready_count", "brochure_only_count",
    "status", "example_provider",
]


def build_matrix(
    town: str,
    sessions: list[dict],
    *,
    exhausted: set[str] | None = None,
    shared_coverage: dict[str, str] | None = None,
    use_llm: bool = True,
) -> list[dict]:
    """Rows for every category. `shared_coverage` maps category → provider town
    (Stage 4 registry hits → covered_via); `exhausted` from the hole cache."""
    sessions = categorize_sessions(sessions, use_llm=use_llm)
    ready = [s for s in sessions if s.get("parent_verdict") == "parent_ready"]
    brochure = [s for s in sessions if s.get("parent_verdict") == "brochure_only"]
    # info_confirmed counts as findable-by-parent (engine v3 verdict)
    ready += [s for s in sessions if s.get("verdict") == "info_confirmed"
              or s.get("parent_verdict") == "info_confirmed"]
    cov_ready = coverage_by_category(ready)
    cov_broch = coverage_by_category(brochure)
    exhausted = exhausted or set()
    shared_coverage = shared_coverage or {}

    rows: list[dict] = []
    for cat in GAP_CATEGORIES:
        r, b = cov_ready.get(cat, []), cov_broch.get(cat, [])
        if r:
            status = "covered"
            example = _host_of(r[0])
        elif cat in shared_coverage:
            status = f"covered_via:{shared_coverage[cat]}"
            example = ""
        elif cat in exhausted:
            status = "exhausted"
            example = _host_of(b[0]) if b else ""
        elif b:
            status = "hole"          # brochure-only is still a hole for the guarantee
            example = _host_of(b[0])
        else:
            status = "hole"
            example = ""
        rows.append(
            {
                "category": cat,
                "tier": "core" if cat in CORE_CATEGORIES else "long_tail",
                "parent_ready_count": len(r),
                "brochure_only_count": len(b),
                "status": status,
                "example_provider": example,
            }
        )
    return rows


def _host_of(session: dict) -> str:
    from urllib.parse import urlparse

    u = session.get("register_url") or session.get("info_url") or ""
    return urlparse(u).netloc.lower().replace("www.", "")


def write_matrix(town: str, rows: list[dict]) -> Path:
    out = town_phase_dir(town, "phase_gap") / "coverage_matrix.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MATRIX_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    update_county_matrix(town, rows)
    return out


def update_county_matrix(town: str, rows: list[dict]) -> Path:
    """Upsert this town's column into the 54-town county grid."""
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    grid: dict[str, dict[str, str]] = {}
    towns: list[str] = []
    if COUNTY_CSV.exists():
        with open(COUNTY_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            towns = [c for c in (reader.fieldnames or []) if c != "category"]
            for r in reader:
                grid[r["category"]] = {t: r.get(t, "") for t in towns}
    if town not in towns:
        towns.append(town)
    for row in rows:
        grid.setdefault(row["category"], {})[town] = row["status"]
    with open(COUNTY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category"] + towns)
        for cat in GAP_CATEGORIES:
            w.writerow([cat] + [grid.get(cat, {}).get(t, "") for t in towns])
    return COUNTY_CSV


def coverage_summary(rows: list[dict]) -> dict:
    core = [r for r in rows if r["tier"] == "core"]
    covered = [r for r in rows if r["status"].startswith("covered")]
    core_covered = [r for r in core if r["status"].startswith("covered")]
    return {
        "categories": len(rows),
        "covered": len(covered),
        "core_total": len(core),
        "core_covered": len(core_covered),
        "core_pct": round(100 * len(core_covered) / max(1, len(core))),
        "holes": [r["category"] for r in rows if r["status"] == "hole"],
    }
