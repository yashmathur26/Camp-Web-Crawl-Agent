"""Part C Stage 6 — Firecrawl handoff manifest.

data/shared/firecrawl_manifest.csv (+ .json): one row per unique provider URL,
deduped county-wide via the provider registry, with category + town tags so the
extraction stage can prioritize and the website can map search terms →
providers immediately.

Filter: in-state, non-aggregator, parent-findable (parent_ready first).
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from config.town_geo import TOWN_GEO
from phase_c.provider_registry import load_registry, registry_coverage

logger = logging.getLogger(__name__)

import os as _os
_SHARED = Path(_os.environ.get("FIREFLY_DATA_ROOT", "data")) / "shared"
MANIFEST_CSV = _SHARED / "firecrawl_manifest.csv"
MANIFEST_JSON = _SHARED / "firecrawl_manifest.json"

COLUMNS = ["url", "provider_name", "host", "towns_served", "categories",
           "parent_verdict", "source_phase", "priority"]


def build_manifest() -> list[dict]:
    reg = load_registry()
    # towns_served: every town whose sharing radius reaches the provider.
    served: dict[str, list[str]] = {h: [] for h in reg}
    for town in TOWN_GEO:
        cov = registry_coverage(town, registry=reg)
        towns_hit = set()
        for cat, provider_town in cov.items():
            for host, entry in reg.items():
                if entry.get("town") == provider_town and cat in (entry.get("categories") or []):
                    towns_hit.add(host)
        for host in towns_hit:
            served[host].append(town)

    rows: list[dict] = []
    for host, entry in sorted(reg.items()):
        urls = entry.get("urls") or []
        if not urls:
            continue
        verdict = "parent_ready" if entry.get("parent_ready") else "info_confirmed"
        rows.append(
            {
                "url": urls[0],
                "provider_name": entry.get("name", ""),
                "host": host,
                "towns_served": ";".join(sorted(set(served.get(host) or [entry.get("town", "")]))),
                "categories": ";".join(entry.get("categories") or []),
                "parent_verdict": verdict,
                "source_phase": entry.get("source_phase", "C"),
                "priority": 1 if entry.get("parent_ready") else 2,
            }
        )
    rows.sort(key=lambda r: (r["priority"], r["host"]))
    return rows


def write_manifest() -> Path:
    rows = build_manifest()
    MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    MANIFEST_JSON.write_text(json.dumps(rows, indent=1))
    logger.info("Firecrawl manifest: %d unique providers -> %s", len(rows), MANIFEST_CSV)
    return MANIFEST_CSV
