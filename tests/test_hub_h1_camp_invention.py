"""HUB ADAPTER ROADMAP — Phase H1 (Camp Invention) acceptance tests. No network."""

from __future__ import annotations

from pathlib import Path

from src.geo_resolve import geo_tag, keep_if_ma
from src.hub_dedup import dedupe_sessions
from src.hubs.camp_invention import parse
from src.season import filter_summer

FIXTURE = Path("data/_fixtures/camp_invention/02421_25mi.html")
EXPECTED_CARDS = 24  # hand-verified against the saved fixture


def _rows():
    return parse(FIXTURE.read_text(encoding="utf-8"))


def test_parser_reproduces_fixture_card_count():
    assert len(_rows()) == EXPECTED_CARDS


def test_every_row_has_register_url_and_summer_date():
    rows = _rows()
    assert all(r["register_url"].endswith(tuple("0123456789")) or "invent.org" in r["register_url"] for r in rows)
    assert all("invent.org" in r["register_url"] for r in rows)
    kept, dropped = filter_summer(rows)
    # Camp Invention runs Jun–Aug; every dated row must fall in the summer window.
    assert dropped == [], [d["dates"] for d in dropped]
    assert len(kept) == EXPECTED_CARDS


def test_geo_from_venue_not_seed():
    rows = _rows()
    for r in rows:
        t = geo_tag(r)
        assert t["geo_source"] == "venue"
        assert t["geo_state"] == "MA", r["name"]
        assert t["geo_zip"], r["name"]
        # never blindly defaulted to the seed town (Lexington): geo_town is only
        # Lexington when the venue is actually in Lexington.
        if t["geo_town"] == "Lexington":
            assert "Lexington" in r.get("venue", "")


def test_zero_rows_outside_ma():
    ma, rejected = keep_if_ma(_rows())
    assert rejected == []
    assert len(ma) == EXPECTED_CARDS


def test_radius_dedup_collapses_duplicate_program():
    # A program appearing in two town searches must emit once.
    rows = _rows()
    doubled = rows + [dict(rows[0], serving_towns=["Arlington"]), dict(rows[0], serving_towns=["Bedford"])]
    deduped, removed = dedupe_sessions(doubled)
    assert removed == 2
    assert len(deduped) == EXPECTED_CARDS
