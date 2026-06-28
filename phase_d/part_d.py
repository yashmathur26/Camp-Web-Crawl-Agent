"""PART D — unified MA-only camp catalog: the three national hubs + US Sports Camps.

This is the "additional step" that runs all of the HUB_ADAPTER_ROADMAP work
(Camp Invention, Skyhawks/Configio, iD Tech via phase_d.hub_run) together with the
previously-built US Sports Camps harvester (config/ussportscamps.py +
scripts/ussportscamps_camps.py), then GEO-TAGS every row so the final catalog
contains ONLY Massachusetts camps.

Pipeline:
    hubs:  run_all_hubs  -> already season-filtered, MA-geo-filtered, deduped
    ussc:  Algolia pull  -> converted to the session shape -> MA geo filter
    merge: combine -> global session_uid dedup -> final MA assertion -> write

Network-touching pieces (`hub_fetch_rows`, `gate_fetch`, `ussc_fetch`) are
INJECTABLE so Part D is unit-testable with no network (fixtures only).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from phase_a.geo_resolve import geo_tag, keep_if_ma
from phase_b.hub_dedup import dedupe_sessions
from phase_d.hub_run import run_all_hubs
from phase_b.platforms import make_session

logger = logging.getLogger(__name__)

USSC_PLATFORM = "ussportscamps"

OUTPUT_FIELDS = [
    "name", "platform", "geo_town", "geo_city", "geo_state", "geo_zip",
    "start_date", "dates", "ages", "price", "register_url", "info_url",
    "serving_towns", "discovered_via", "session_uid",
]


# --------------------------------------------------------------------------- #
# US Sports Camps -> session shape
# --------------------------------------------------------------------------- #
def _ussc_to_session(row: dict) -> dict:
    """Convert one US Sports Camps Algolia row into a make_session-style record."""
    city = (row.get("city") or "").strip()
    state = (row.get("state") or "").strip()
    venue = ", ".join(p for p in (city, state) if p)
    dates = (row.get("session_dates") or "")
    start = dates.split(";")[0].split("–")[0].split("-")[0].strip()
    ages = ""
    if row.get("min_age") != "" and row.get("max_age") != "":
        ages = f"{row.get('min_age')}-{row.get('max_age')}"
    s = make_session(
        row.get("camp_title", ""),
        row.get("camp_url", ""),
        info_url=row.get("camp_url", ""),
        details_text=" | ".join(p for p in (row.get("brand", ""), row.get("sport", ""), venue) if p),
        platform=USSC_PLATFORM,
        dates=dates,
        ages=ages,
        source_url="https://www.ussportscamps.com",
        kind="session",
        name_source="adapter",
    )
    s["venue"] = venue
    s["venue_city"] = city
    s["venue_state"] = state
    s["start_date"] = start
    s["object_id"] = row.get("object_id", "")
    s["serving_towns"] = [row.get("town")] if row.get("town") else []
    s["_hub"] = USSC_PLATFORM
    s["sport"] = row.get("sport", "")
    s["parent_ready"] = True
    s["registrable"] = True
    return s


def _default_ussc_fetch(towns: list[str], *, per_sport: int, delay: float) -> list[dict]:
    """Live US Sports Camps pull via the existing Algolia harvester."""
    from scripts.ussportscamps_camps import fetch_sport_slugs
    from scripts.ussportscamps_camps import run as ussc_run

    sports = fetch_sport_slugs()
    return ussc_run(towns, per_sport, sports, False, delay)


def ussportscamps_sessions(
    towns: list[str],
    *,
    per_sport: int = 10,
    delay: float = 0.15,
    ussc_fetch=None,
) -> tuple[list[dict], int]:
    """Return (MA-only sessions, non_ma_rejected_count) from US Sports Camps.

    The raw Algolia pull ranks by distance with aroundRadius='all', so it returns
    out-of-state camps too. Part D's whole point is to keep ONLY MA camps, so we
    geo-filter on the venue state here.
    """
    fetch = ussc_fetch or (lambda ts: _default_ussc_fetch(ts, per_sport=per_sport, delay=delay))
    raw = fetch(towns)
    sessions = [_ussc_to_session(r) for r in raw]
    ma, rejected = keep_if_ma(sessions)
    return ma, len(rejected)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_part_d(
    *,
    towns: list[str] | None = None,
    hubs: list[str] | None = None,
    include_ussc: bool = True,
    per_sport: int = 10,
    ussc_delay: float = 0.15,
    hub_fetch_rows=None,
    gate_fetch=None,
    run_gate: bool = True,
    ussc_fetch=None,
    out_dir: str | Path | None = None,
    ts: str = "",
) -> dict:
    """Run all hubs + US Sports Camps, geo-tag to MA only, dedup, and write outputs.

    Returns a result dict with rows, per-source stats, and a reconciliation report.
    """
    import asyncio

    hub_res = asyncio.run(run_all_hubs(
        towns=towns, hubs=hubs, fetch_rows=hub_fetch_rows, gate_fetch=gate_fetch,
        run_gate=run_gate, ts=ts,
    ))
    hub_rows = hub_res["rows"]

    ussc_rows: list[dict] = []
    ussc_rejected = 0
    if include_ussc:
        ussc_rows, ussc_rejected = ussportscamps_sessions(
            towns or [], per_sport=per_sport, delay=ussc_delay, ussc_fetch=ussc_fetch,
        )

    combined = hub_rows + ussc_rows
    deduped, removed = dedupe_sessions(combined)

    # Final MA assertion pass: geo-tag every row; drop anything that isn't MA.
    final, dropped_non_ma = keep_if_ma(deduped)
    for r in final:
        # ensure session_uid present for output
        r.setdefault("session_uid", "")

    reconciliation = {
        "total_sessions": len(final),
        "hub_sessions": len(hub_rows),
        "ussportscamps_sessions": len(ussc_rows),
        "ussportscamps_non_ma_rejected": ussc_rejected,
        "duplicates_collapsed": removed,
        "final_non_ma_dropped": len(dropped_non_ma),
        "per_hub": hub_res["reconciliation"]["per_hub_contribution"],
        "cross_hub_duplicates_collapsed": hub_res["reconciliation"]["cross_hub_duplicates_collapsed"],
    }

    if out_dir is None:
        from shared.data_layout import DATA_ROOT

        out_dir = DATA_ROOT / "part_d"
    out_dir = Path(out_dir)
    csv_path = out_dir / "part_d_ma_camps.csv"
    write_outputs(final, csv_path)
    logger.info("Part D reconciliation: %s", reconciliation)
    return {
        "rows": final,
        "hubs": hub_res["hubs"],
        "reconciliation": reconciliation,
        "alarms": hub_res["alarms"],
        "csv_path": str(csv_path),
    }


def write_outputs(rows: list[dict], csv_path: str | Path) -> None:
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            tagged = geo_tag(r)
            out = {k: tagged.get(k, "") for k in OUTPUT_FIELDS}
            out["serving_towns"] = ";".join(r.get("serving_towns", []) or [])
            out["discovered_via"] = ";".join(r.get("discovered_via", []) or [])
            w.writerow(out)
