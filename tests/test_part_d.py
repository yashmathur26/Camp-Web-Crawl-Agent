"""PART D — unified MA-only catalog (hubs + US Sports Camps) tests. No network."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import src.hub_run as hub_run
import src.hub_safeguards as safeguards
import src.part_d as part_d
from src.geo_resolve import geo_tag
from src.hub_dedup import session_uid
from src.hubs.camp_invention import parse as parse_ci
from src.hubs.configio import parse as parse_cfg
from src.hubs.idtech import parse_reg_flow

CI = Path("data/_fixtures/camp_invention/02421_25mi.html")
CFG = Path("data/_fixtures/configio/skyhawks_02421_10mi.html")
IDT = Path("data/_fixtures/idtech/bentley_campus.html")
BENTLEY = "https://www.idtech.com/locations/massachusetts-summer-camps/bentley-university"


def _hub_fetch(hub_name, seed, existing):
    async def _ret(rows):
        return [r for r in rows if r.get("register_url") not in existing]

    if seed["town"] != "Lexington":
        return _ret([])
    if hub_name == "camp_invention":
        return _ret(parse_ci(CI.read_text(encoding="utf-8")))
    if hub_name == "skyhawks":
        return _ret(parse_cfg(CFG.read_text(encoding="utf-8")))
    return _ret(parse_reg_flow(IDT.read_text(encoding="utf-8"), campus_url=BENTLEY, campus_venue="Waltham, MA"))


def _ussc_fetch(towns):
    # A mix: 2 MA camps and 2 out-of-state camps (must be rejected by geo).
    return [
        {"town": "Lexington", "sport": "Basketball", "camp_title": "Nike Basketball Camp Bentley",
         "brand": "Nike", "min_age": 8, "max_age": 14, "session_dates": "7/6/2026–7/10/2026",
         "city": "Waltham", "state": "MA", "camp_url": "https://www.ussportscamps.com/basketball/nike/waltham",
         "object_id": "USSC1"},
        {"town": "Lexington", "sport": "Soccer", "camp_title": "Challenger Soccer Concord",
         "brand": "Challenger", "min_age": 6, "max_age": 12, "session_dates": "7/13/2026–7/17/2026",
         "city": "Concord", "state": "MA", "camp_url": "https://www.ussportscamps.com/soccer/challenger/concord",
         "object_id": "USSC2"},
        {"town": "Lexington", "sport": "Tennis", "camp_title": "Nike Tennis Nashua",
         "brand": "Nike", "min_age": 10, "max_age": 16, "session_dates": "7/6/2026–7/10/2026",
         "city": "Nashua", "state": "NH", "camp_url": "https://www.ussportscamps.com/tennis/nike/nashua",
         "object_id": "USSC3"},
        {"town": "Lexington", "sport": "Golf", "camp_title": "Nike Golf Providence",
         "brand": "Nike", "min_age": 10, "max_age": 16, "session_dates": "7/20/2026–7/24/2026",
         "city": "Providence", "state": "RI", "camp_url": "https://www.ussportscamps.com/golf/nike/providence",
         "object_id": "USSC4"},
    ]


@pytest.fixture(autouse=True)
def _isolate_io(tmp_path, monkeypatch):
    monkeypatch.setattr(safeguards, "SNAPSHOT_DIR", tmp_path / "snap")
    monkeypatch.setattr(hub_run, "KPI_LEDGER", tmp_path / "kpi.csv")


def test_ussportscamps_geo_filter_keeps_only_ma():
    ma, rejected = part_d.ussportscamps_sessions(["Lexington"], ussc_fetch=_ussc_fetch)
    assert rejected == 2  # NH + RI dropped
    states = {geo_tag(r)["geo_state"] for r in ma}
    assert states == {"MA"}
    assert len(ma) == 2


def test_full_state_name_normalized_to_ma():
    # Algolia returns the full state name "Massachusetts" — it must normalize to
    # the 2-letter "MA" label, not "MASSACHUSETTS" (live-found bug).
    def fetch(towns):
        return [{
            "town": "Lexington", "sport": "Basketball", "camp_title": "Hoops Camp",
            "min_age": 8, "max_age": 14, "session_dates": "7/6/2026",
            "city": "Waltham", "state": "Massachusetts",
            "camp_url": "https://www.ussportscamps.com/x", "object_id": "Z1",
        }]

    ma, rejected = part_d.ussportscamps_sessions(["Lexington"], ussc_fetch=fetch)
    assert rejected == 0
    assert {geo_tag(r)["geo_state"] for r in ma} == {"MA"}


def test_run_part_d_unified_ma_only(tmp_path):
    res = part_d.run_part_d(
        towns=["Lexington"],
        hub_fetch_rows=_hub_fetch,
        ussc_fetch=_ussc_fetch,
        run_gate=False,
        out_dir=tmp_path / "out",
        ts="2026-06-15",
    )
    rows = res["rows"]
    assert rows

    # Every final row is MA.
    assert all(geo_tag(r)["geo_state"] == "MA" for r in rows)

    # US Sports Camps contributed its 2 MA camps; 2 non-MA were rejected.
    assert res["reconciliation"]["ussportscamps_sessions"] == 2
    assert res["reconciliation"]["ussportscamps_non_ma_rejected"] == 2
    assert res["reconciliation"]["final_non_ma_dropped"] == 0

    # All three hubs + ussportscamps platforms present.
    platforms = {r["platform"] for r in rows}
    assert "camp_invention" in platforms
    assert "configio" in platforms
    assert "idtech" in platforms
    assert "ussportscamps" in platforms

    # Zero duplicate session_uids.
    uids = [session_uid(r) for r in rows]
    assert len(uids) == len(set(uids))

    # CSV written with MA-only rows.
    csv_path = Path(res["csv_path"])
    assert csv_path.exists()
    with csv_path.open() as f:
        out_rows = list(csv.DictReader(f))
    assert out_rows
    assert all(r["geo_state"] == "MA" for r in out_rows)
