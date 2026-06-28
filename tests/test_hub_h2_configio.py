"""HUB ADAPTER ROADMAP — Phase H2 (Skyhawks/Configio) acceptance tests. No network."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from phase_a.geo_resolve import geo_tag, keep_if_ma
from phase_b.hub_dedup import dedupe_sessions
from phase_d.hubs.configio import parse
from phase_a.season import filter_summer

FIXTURE = Path("data/_fixtures/configio/skyhawks_02421_10mi.html")
EXPECTED_CARDS = 22  # hand-verified against the saved fixture


def _rows():
    return parse(FIXTURE.read_text(encoding="utf-8"))


def test_parser_reproduces_exact_card_count():
    assert len(_rows()) == EXPECTED_CARDS


def test_available_is_registrable_full_is_not():
    rows = _rows()
    for r in rows:
        if r["status_text"] == "Available":
            assert r["registrable"] is True, r["name"]
        if r["status_text"] == "Full":
            assert r["registrable"] is False, r["name"]


def test_external_register_host_is_municipal_not_skyhawks():
    rows = _rows()
    ext = [r for r in rows if r["_register_node"] == "external"]
    assert ext, "fixture should contain external-register cards"
    for r in ext:
        host = urlparse(r["register_url"]).netloc.lower()
        assert "skyhawks.com" not in host, r["register_url"]
        assert any(s in host for s in ("myrec.com", "activityreg.com", "vermontsystems.com")), host


def test_season_filter_removes_non_summer():
    kept, dropped = filter_summer(_rows())
    for r in kept:
        # every kept dated row starts in a summer month
        if r.get("season_source") == "dated":
            assert r["start_date"][5:7] in ("06", "07", "08"), r["start_date"]
    assert len(kept) + len(dropped) == EXPECTED_CARDS


def test_geo_from_venue_never_seed_zip():
    rows = _rows()
    for r in rows:
        t = geo_tag(r)
        assert t["geo_zip"] != "02421", r["name"]  # never the Lexington seed
        assert t["geo_source"] == "venue"
    ma, rejected = keep_if_ma(rows)
    assert rejected == []  # this 10mi MA search is entirely MA
    assert len(ma) == EXPECTED_CARDS


def test_intra_source_dedup_collapses_identical_cards():
    # The fixture genuinely lists one Flag Football session twice (same name,
    # Burlington 01803, 8/24/2026) -> 22 cards, 21 unique sessions.
    rows = _rows()
    deduped, removed = dedupe_sessions(rows)
    assert removed == 1
    assert len(deduped) == EXPECTED_CARDS - 1


def test_cross_adapter_dedup_collapses_to_one_uid():
    # A Skyhawks card whose external register routes into a MyRec ProgramID must
    # collapse with the direct-MyRec adapter row for that same ProgramID.
    rows = _rows()
    myrec_card = next(
        r for r in rows if "myrec.com" in r["register_url"] and "ProgramID" in r["register_url"]
    )
    direct = {
        "register_url": myrec_card["register_url"],
        "platform": "myrec",
        "name": myrec_card["name"],
        "serving_towns": ["Carlisle"],
    }
    deduped, removed = dedupe_sessions(rows + [direct])
    # 1 intra-source dup + 1 cross-adapter twin both collapse.
    assert removed == 2
    assert len(deduped) == EXPECTED_CARDS - 1
    merged = next(r for r in deduped if r["register_url"] == myrec_card["register_url"])
    assert "myrec" in merged["discovered_via"]
    assert "configio" in merged["discovered_via"]
