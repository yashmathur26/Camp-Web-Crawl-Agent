"""HUB ADAPTER ROADMAP — Phase H3 (iD Tech) acceptance tests. No network."""

from __future__ import annotations

from pathlib import Path

from phase_a.geo_resolve import geo_tag
from phase_d.hubs.idtech import parse_locations, parse_reg_flow

LOC_FIXTURE = Path("data/_fixtures/idtech/location-search_lexington.html")
CAMPUS_FIXTURE = Path("data/_fixtures/idtech/bentley_campus.html")
BENTLEY_URL = "https://www.idtech.com/locations/massachusetts-summer-camps/bentley-university"

# Hand-verified against the saved fixtures.
KNOWN_MA_CAMPUSES = {"Bentley University", "MIT Campus", "Olin College of Engineering",
                     "Curry College", "UMass Amherst"}
EXPECTED_OPEN_SESSIONS = 10


def _locations():
    return parse_locations(LOC_FIXTURE.read_text(encoding="utf-8"))


def _reg_flow():
    return parse_reg_flow(CAMPUS_FIXTURE.read_text(encoding="utf-8"),
                          campus_url=BENTLEY_URL, campus_venue="Waltham, MA")


# --- Hop 1 ------------------------------------------------------------------
def test_location_search_returns_known_ma_campuses():
    ma = {c["name"] for c in _locations() if "massachusetts" in c["state_slug"]}
    assert KNOWN_MA_CAMPUSES <= ma, KNOWN_MA_CAMPUSES - ma


def test_campus_venue_is_real_town():
    bentley = next(c for c in _locations() if c["name"] == "Bentley University")
    assert bentley["venue"] == "Waltham, MA"


# --- Hops 2/3 ---------------------------------------------------------------
def test_reg_flow_emits_only_open_priced_cells():
    rows = _reg_flow()
    assert len(rows) == EXPECTED_OPEN_SESSIONS
    assert all(r["status_text"] == "Open" for r in rows)
    assert all(r["price"] for r in rows)  # zero sessions without a price


def test_register_url_shared_info_url_distinct():
    rows = _reg_flow()
    assert len({r["register_url"] for r in rows}) == 1  # shared reg-flow page
    # one info_url per distinct course
    courses = {r["product_id"] for r in rows}
    assert len({r["info_url"] for r in rows}) == len(courses)
    assert all("reg-flow" in r["register_url"] and "lid=" in r["register_url"] for r in rows)


def test_reg_flow_geo_from_campus_venue():
    rows = _reg_flow()
    for r in rows:
        t = geo_tag(r)
        assert t["geo_state"] == "MA"
        assert t["geo_town"] == "Waltham"


def test_empty_and_try_online_cells_emit_nothing():
    # A course-row with a date range but a non-Open / Try-online cell -> no session.
    empty = (
        '<div class="course-row" data-id-product-id="999">'
        '<h5 class="course-name">Fake Camp</h5>Ages: 7-9 from <span>$100 USD</span>'
        '<div class="cell empty">>Jul 6-10< Try online</div></div>'
    )
    assert parse_reg_flow(empty, campus_url=BENTLEY_URL) == []
    no_price = (
        '<div class="course-row" data-id-product-id="998">'
        '<h5 class="course-name">No Price Camp</h5>Ages: 7-9'
        '<div class="cell">>Jul 6-10< text-open Open</div></div>'
    )
    assert parse_reg_flow(no_price, campus_url=BENTLEY_URL) == []
