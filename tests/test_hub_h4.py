"""HUB ADAPTER ROADMAP — Phase H4 (orchestration/reconciliation) tests. No network."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import src.hub_run as hub_run
import src.hub_safeguards as safeguards
from src.hub_dedup import session_uid
from src.hubs.camp_invention import parse as parse_ci
from src.hubs.configio import parse as parse_cfg
from src.hubs.idtech import parse_locations, parse_reg_flow

CI = Path("data/_fixtures/camp_invention/02421_25mi.html")
CFG = Path("data/_fixtures/configio/skyhawks_02421_10mi.html")
IDT = Path("data/_fixtures/idtech/bentley_campus.html")
BENTLEY = "https://www.idtech.com/locations/massachusetts-summer-camps/bentley-university"


def _fixture_fetch_rows(hub_name, seed, existing):
    # Only the Lexington seed yields rows (simulates a single representative pull);
    # other towns return [] so the run is bounded and deterministic.
    async def _noop():
        return []

    if seed["town"] != "Lexington":
        return _noop()

    if hub_name == "camp_invention":
        rows = parse_ci(CI.read_text(encoding="utf-8"))
    elif hub_name == "skyhawks":
        rows = parse_cfg(CFG.read_text(encoding="utf-8"))
    else:
        rows = parse_reg_flow(IDT.read_text(encoding="utf-8"), campus_url=BENTLEY, campus_venue="Waltham, MA")

    async def _ret():
        return [r for r in rows if r.get("register_url") not in existing]

    return _ret()


@pytest.fixture(autouse=True)
def _isolate_io(tmp_path, monkeypatch):
    monkeypatch.setattr(safeguards, "SNAPSHOT_DIR", tmp_path / "snap")
    monkeypatch.setattr(hub_run, "KPI_LEDGER", tmp_path / "kpi.csv")


def test_run_all_hubs_offline():
    res = asyncio.run(hub_run.run_all_hubs(
        towns=["Lexington", "Arlington"], fetch_rows=_fixture_fetch_rows, run_gate=False, ts="2026-06-15",
    ))
    rows = res["rows"]
    assert rows, "should emit sessions"

    # Zero duplicate session_uids in the final reconciled catalog (H4 acceptance).
    uids = [session_uid(r) for r in rows]
    assert len(uids) == len(set(uids)), "duplicate session_uid in final catalog"

    # Zero sessions outside MA.
    from src.geo_resolve import geo_tag
    assert all(geo_tag(r)["geo_state"] == "MA" for r in rows)

    # Zero sessions outside the summer window (all carry a season reason).
    for r in rows:
        if r.get("season_source") == "dated":
            assert r["start_date"][5:7] in ("06", "07", "08"), r.get("start_date")

    # Each hub contributed.
    assert set(res["hubs"]) == {"camp_invention", "skyhawks", "idtech"}
    for name, s in res["hubs"].items():
        assert s["emitted"] > 0, name

    # KPI ledger written.
    assert hub_run.KPI_LEDGER.exists()
    body = hub_run.KPI_LEDGER.read_text()
    assert "camp_invention" in body and "skyhawks" in body and "idtech" in body


def test_zero_floor_alarm_when_hub_empty():
    def empty_fetch(hub_name, seed, existing):
        async def _e():
            return []
        return _e()

    res = asyncio.run(hub_run.run_hub("skyhawks", towns=["Lexington"], fetch_rows=empty_fetch, run_gate=False))
    assert any("ZERO-FLOOR" in a for a in res["alarms"])
