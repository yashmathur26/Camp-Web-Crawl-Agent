"""Curated K-12 / trade schools per town (hybrid discovery — Thread 3).

The RELIABLE half of school discovery. Smart depth (operator decision):
  - private / prep / independent  -> per-institution (highest camp yield)
  - public HIGH schools           -> per-institution
  - trade / vocational / technical-> per-institution
  - public ELEMENTARY / MIDDLE    -> NOT listed here; covered by the town-level
    district query ("{town} public schools summer programs") in the Phase A pool,
    because individual elementary schools almost never run their own camps.

Dynamic discovery in src/run.py finds schools not listed here, so this table is a
seed for the pilot town, not an allowlist.

`type` ∈ {"private", "public_high", "public_district", "trade"}.
Hosts are primary domains (no www). Verified entries only.
"""

from __future__ import annotations

SCHOOLS_BY_TOWN: dict[str, list[dict]] = {
    "Waltham": [
        {"name": "Waltham Public Schools", "host": "walthampublicschools.org",
         "type": "public_district"},
        {"name": "Waltham High School", "host": "walthampublicschools.org",
         "type": "public_high"},
        {"name": "Gann Academy", "host": "gannacademy.org", "type": "private"},
        {"name": "Chapel Hill-Chauncy Hall School", "host": "chch.org", "type": "private"},
    ],
}

_CAMP_HOSTING_TYPES = {"private", "public_high", "trade"}


def schools_for(town: str) -> list[dict]:
    """Curated schools for a town (empty if none listed; dynamic discovery fills
    the gap at run time)."""
    return SCHOOLS_BY_TOWN.get(town, [])


def school_counts(town: str) -> dict[str, int]:
    """Counts by type for the budget's institution boost."""
    counts = {"private": 0, "public_high": 0, "public_district": 0, "trade": 0}
    for s in schools_for(town):
        t = s.get("type", "")
        if t in counts:
            counts[t] += 1
    return counts
