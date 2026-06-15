"""HUB ADAPTER ROADMAP — Phase H0 acceptance tests (falsifiable, no network)."""

from __future__ import annotations

import asyncio

import pytest

from config.hubs import HUBS, hub_search_url, template_fields
from config.towns import TOWN_ZIPS, validate_town_zips
from src.hub_dedup import dedupe_sessions, rows_match
from src.hub_safeguards import apply_host_bounds, register_url_gate, zero_floor_alarm
from src.season import filter_summer, in_summer_window


# --- H0.1 -------------------------------------------------------------------
def test_all_54_towns_have_valid_zips():
    assert validate_town_zips() == []
    assert len(TOWN_ZIPS) == 54


def test_zip_band_and_state():
    import re

    band = re.compile(r"^0(?:1[4-9]|2[0-4])\d{2}$")
    for town, seed in TOWN_ZIPS.items():
        assert band.match(seed["zip"]), (town, seed["zip"])
        assert seed["state"] == "MA"


# --- H0.2 -------------------------------------------------------------------
def test_all_three_templates_render():
    assert set(HUBS) == {"camp_invention", "skyhawks", "idtech"}
    assert hub_search_url("camp_invention", zip="02421", radius=25).startswith("https://www.invent.org")
    assert "zip=02421&zipdis=10" in hub_search_url("skyhawks", zip="02421", radius=10)
    assert "Lexington,+MA,+USA" in hub_search_url("idtech", city="Lexington", state="MA", page=1)


def test_template_missing_value_raises():
    with pytest.raises(ValueError):
        hub_search_url("skyhawks", zip="")


def test_template_fields_detected():
    assert template_fields(HUBS["idtech"]["search_template"]) == {"city", "state", "page"}


# --- H0.4 : known-id path, >=3 positive, >=3 negative -----------------------
def _mk(url, **kw):
    return {"register_url": url, "platform": "configio", **kw}


def test_session_uid_known_id_positive():
    pairs = [
        ("https://t.myrec.com/info/activities/program_details.aspx?ProgramID=7",
         "https://t.myrec.com/info/activities/program_details.aspx?ProgramID=7&utm=x"),
        ("https://x.myvscloud.com/webtrac/web/iteminfo.html?Module=AR&FMID=99",
         "https://x.myvscloud.com/webtrac/web/iteminfo.html?FMID=99&Module=AR&_csrf_token=z"),
        ("https://register.skyhawks.com/pd/12345/flag-football",
         "https://register.skyhawks.com/pd/12345/other-slug"),
    ]
    for a, b in pairs:
        assert rows_match(_mk(a), _mk(b)), (a, b)


def test_session_uid_known_id_negative():
    pairs = [
        ("https://t.myrec.com/info/activities/program_details.aspx?ProgramID=7",
         "https://t.myrec.com/info/activities/program_details.aspx?ProgramID=8"),
        ("https://x.myvscloud.com/webtrac/web/iteminfo.html?Module=AR&FMID=99",
         "https://x.myvscloud.com/webtrac/web/iteminfo.html?Module=AR&FMID=100"),
        ("https://register.skyhawks.com/pd/12345/x",
         "https://register.skyhawks.com/pd/54321/x"),
    ]
    for a, b in pairs:
        assert not rows_match(_mk(a), _mk(b)), (a, b)


# --- H0.4 : fuzzy path, >=3 positive, >=3 negative --------------------------
def _fz(name, zip_, date):
    return {"name": name, "geo_zip": zip_, "start_date": date}


def test_session_uid_fuzzy_positive():
    cases = [
        (_fz("Flag Football Camp", "01803", "2026-07-06"), _fz("Camp Flag Football", "01803", "2026-07-06")),
        (_fz("Mad Science Summer Camp", "02472", "2026-07-13"), _fz("Summer Camp Mad Science", "02472", "2026-07-13")),
        (_fz("Lego Robotics Week 1", "01742", "2026-08-03"), _fz("Week 1 Lego Robotics", "01742", "2026-08-03")),
    ]
    for a, b in cases:
        assert rows_match(a, b), (a, b)


def test_session_uid_fuzzy_negative():
    cases = [
        (_fz("Flag Football Camp", "01803", "2026-07-06"), _fz("Flag Football Camp", "01803", "2026-08-10")),  # diff date
        (_fz("Flag Football Camp", "01803", "2026-07-06"), _fz("Flag Football Camp", "02472", "2026-07-06")),  # diff zip
        (_fz("Soccer Camp", "01803", "2026-07-06"), _fz("Tennis Academy", "01803", "2026-07-06")),  # diff name
    ]
    for a, b in cases:
        assert not rows_match(a, b), (a, b)


def test_dedupe_collapses_and_counts():
    rows = [
        _mk("https://t.myrec.com/info/activities/program_details.aspx?ProgramID=7", serving_towns=["Burlington"]),
        {"register_url": "https://t.myrec.com/info/activities/program_details.aspx?ProgramID=7&x=1",
         "platform": "myrec", "serving_towns": ["Lexington"]},
    ]
    deduped, removed = dedupe_sessions(rows)
    assert len(deduped) == 1 and removed == 1
    assert set(deduped[0]["serving_towns"]) == {"Burlington", "Lexington"}
    assert set(deduped[0]["discovered_via"]) == {"configio", "myrec"}


# --- H0.7 : explosion cap exemption -----------------------------------------
def test_hub_exempt_from_explosion_cap():
    rows = [{"platform": "configio", "_hub": "skyhawks"} for _ in range(30)]
    kept, _ = apply_host_bounds(rows, is_hub=True)
    assert len(kept) == 30


def test_nonhub_capped():
    rows = [{"platform": "x", "_hub": "h"} for _ in range(80)]
    kept, alarms = apply_host_bounds(rows, is_hub=False)
    assert len(kept) == 60
    assert alarms


def test_zero_floor_alarm():
    assert zero_floor_alarm("skyhawks", 0)
    assert zero_floor_alarm("skyhawks", 5) is None


# --- H0.6 : season filter ---------------------------------------------------
def test_season_jan_dropped_jul_kept():
    assert in_summer_window("July 6, 2026")[0]
    assert not in_summer_window("January 15, 2026")[0]
    kept, dropped = filter_summer([{"dates": "7/6/2026"}, {"dates": "1/15/2026"}])
    assert len(kept) == 1 and len(dropped) == 1


# --- H0.7 : register gate (no network; injected fetcher) --------------------
def test_register_gate_demotes_only_on_positive_failure():
    async def fetch(url):
        return {
            "ok": (200, '<a href="/cart">Add to Cart</a>'),
            "dead": (404, ""),
            "noaff": (200, "<p>brochure</p>"),
            "down": (0, ""),
        }[url]

    rows = [
        {"register_url": "ok", "parent_ready": True, "registrable": True},
        {"register_url": "dead", "parent_ready": True, "registrable": True},
        {"register_url": "noaff", "parent_ready": True, "registrable": True},
        {"register_url": "down", "parent_ready": True, "registrable": True},
    ]
    res = asyncio.run(register_url_gate(rows, fetch))
    assert res[0]["registrable"] is True
    assert res[1]["registrable"] is False
    assert res[2]["registrable"] is False
    assert res[3]["registrable"] is True  # unchecked is NOT demoted
