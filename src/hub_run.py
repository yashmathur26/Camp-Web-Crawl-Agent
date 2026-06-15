"""HUB ADAPTER ROADMAP H4 — hub orchestration, reconciliation, KPI ledger.

A hub pass runs ALONGSIDE the B.5 navigator (it never feeds into it). For each
hub, for each town seed:

    fetch -> parse -> season-filter -> geo-resolve(MA) -> register_url gate
          -> cross/intra dedup (session_uid) -> emit

Hubs are exempt from the single-provider explosion cap; a hub returning 0 across
all towns raises a zero-floor alarm; per-hub snapshots diff run-over-run.

Everything network-touching is INJECTED (`fetch_rows`, `gate_fetch`) so this
module is unit-testable with no network (golden fixtures only).
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from config.hubs import HUBS
from config.towns import TOWN_ZIPS
from src.hub_dedup import dedupe_sessions
from src.hub_safeguards import (
    apply_host_bounds,
    diff_snapshot,
    register_url_gate,
    write_snapshot,
    zero_floor_alarm,
)
from src.hubs import camp_invention as _camp_invention
from src.hubs import configio as _configio
from src.hubs import idtech as _idtech
from src.season import filter_summer

logger = logging.getLogger(__name__)

# hub name -> adapter module (each exposes async fetch(zip, city, state, radius, existing))
HUB_ADAPTERS = {
    "camp_invention": _camp_invention,
    "skyhawks": _configio,
    "idtech": _idtech,
}

KPI_LEDGER = Path("data/shared/hub_eval_history.csv")


def town_seeds(towns: list[str] | None = None) -> list[dict]:
    """Seed dicts (town, zip, city, state) for the requested towns (default all 54)."""
    names = towns or list(TOWN_ZIPS.keys())
    seeds = []
    for t in names:
        s = TOWN_ZIPS.get(t)
        if s:
            seeds.append({"town": t, **s})
    return seeds


async def _default_fetch_rows(hub_name: str, seed: dict, existing: set[str]) -> list[dict]:
    adapter = HUB_ADAPTERS[hub_name]
    radius = HUBS[hub_name].get("radius_miles") or 0
    return await adapter.fetch(seed["zip"], seed["city"], seed["state"], radius, existing)


async def run_hub(
    hub_name: str,
    *,
    towns: list[str] | None = None,
    fetch_rows=None,
    gate_fetch=None,
    run_gate: bool = True,
    ts: str = "",
) -> dict:
    """Run one hub across town seeds. Returns {hub, rows, stats, alarms}.

    fetch_rows(hub_name, seed, existing) -> list[rows]  (defaults to live adapter)
    gate_fetch(url) -> (status, html)  (register_url gate; skipped if None)
    """
    if hub_name not in HUB_ADAPTERS:
        raise ValueError(f"unknown hub {hub_name!r}")
    fetch_rows = fetch_rows or _default_fetch_rows
    seeds = town_seeds(towns)

    raw: list[dict] = []
    existing: set[str] = set()
    for seed in seeds:
        rows = await fetch_rows(hub_name, seed, existing)
        for r in rows:
            r.setdefault("serving_towns", [])
            if seed["town"] not in r["serving_towns"]:
                r["serving_towns"].append(seed["town"])
            r.setdefault("_hub", hub_name)
            existing.add(r.get("register_url", ""))
        raw.extend(rows)

    raw_count = len(raw)

    # season filter (start_date summer window)
    in_season, off_season = filter_summer(raw)

    # geo resolve -> MA only (venue-based; never the seed ZIP)
    from src.geo_resolve import keep_if_ma

    ma_rows, geo_rejected = keep_if_ma(in_season)

    # register_url gate (asymmetric demotion)
    if run_gate and gate_fetch is not None:
        ma_rows = await register_url_gate(ma_rows, gate_fetch)

    # dedup (intra + cross path) by session_uid
    deduped, removed = dedupe_sessions(ma_rows)

    # hub-exempt host bounds + zero-floor alarm
    bounded, bound_alarms = apply_host_bounds(deduped, is_hub=True)
    alarms = list(bound_alarms)
    zfa = zero_floor_alarm(hub_name, len(bounded))
    if zfa:
        alarms.append(zfa)

    # snapshot diff (per-town counts) then persist
    counts = {}
    for r in bounded:
        for t in r.get("serving_towns", []) or ["_"]:
            counts[t] = counts.get(t, 0) + 1
    alarms.extend(diff_snapshot(hub_name, counts))
    write_snapshot(hub_name, counts, ts=ts)

    pr = sum(1 for r in bounded if r.get("parent_ready"))
    gated_pass = sum(1 for r in bounded if r.get("_gate_reason") == "200+affordance")
    stats = {
        "hub": hub_name,
        "raw": raw_count,
        "season_rejected": len(off_season),
        "geo_rejected": len(geo_rejected),
        "duplicates_collapsed": removed,
        "emitted": len(bounded),
        "parent_ready": pr,
        "parent_ready_rate": round(pr / len(bounded), 3) if bounded else 0.0,
        "gate_pass": gated_pass,
        "gate_pass_rate": round(gated_pass / pr, 3) if pr else 0.0,
    }
    logger.info("hub %s: %s", hub_name, stats)
    return {"hub": hub_name, "rows": bounded, "stats": stats, "alarms": alarms}


async def run_all_hubs(
    *,
    towns: list[str] | None = None,
    hubs: list[str] | None = None,
    fetch_rows=None,
    gate_fetch=None,
    run_gate: bool = True,
    ts: str = "",
) -> dict:
    """Run every hub, then a global session_uid reconciliation across hubs.

    Returns {hubs: {name: stats}, rows, reconciliation, alarms}.
    """
    names = hubs or list(HUB_ADAPTERS.keys())
    per_hub: dict[str, dict] = {}
    all_rows: list[dict] = []
    alarms: list[str] = []
    for name in names:
        res = await run_hub(
            name, towns=towns, fetch_rows=fetch_rows, gate_fetch=gate_fetch,
            run_gate=run_gate, ts=ts,
        )
        per_hub[name] = res["stats"]
        all_rows.extend(res["rows"])
        alarms.extend(res["alarms"])

    # H4.2 global reconciliation across hubs
    reconciled, cross_removed = dedupe_sessions(all_rows)
    reconciliation = {
        "total_sessions": len(reconciled),
        "per_hub_contribution": {n: per_hub[n]["emitted"] for n in per_hub},
        "cross_hub_duplicates_collapsed": cross_removed,
    }
    _append_kpi_ledger(per_hub, reconciliation, ts=ts)
    return {
        "hubs": per_hub,
        "rows": reconciled,
        "reconciliation": reconciliation,
        "alarms": alarms,
    }


def _append_kpi_ledger(per_hub: dict, reconciliation: dict, *, ts: str = "") -> None:
    """H4.4 — append one KPI row per hub per run to eval_history."""
    KPI_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new_file = not KPI_LEDGER.exists()
    with KPI_LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts", "hub", "emitted", "parent_ready", "parent_ready_rate",
                        "gate_pass_rate", "duplicates_collapsed", "geo_rejected",
                        "season_rejected", "cross_hub_duplicates_collapsed"])
        for name, s in per_hub.items():
            w.writerow([
                ts, name, s["emitted"], s["parent_ready"], s["parent_ready_rate"],
                s["gate_pass_rate"], s["duplicates_collapsed"], s["geo_rejected"],
                s["season_rejected"], reconciliation["cross_hub_duplicates_collapsed"],
            ])
