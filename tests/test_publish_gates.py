"""Task 4.2: publish gates — verified-only catalog, date sanity, audience guard."""

from __future__ import annotations

from datetime import date

from src.deliverables import apply_publish_gates, parse_date_range


def _row(**kw) -> dict:
    base = {
        "provider_host": "camp.org",
        "name": "Art Camp",
        "register_url": "https://camp.org/register",
        "platform": "custom",
        "dates": "July 7-11",
        "ages": "6-12",
        "price": "$300",
        "kind": "session",
        "source_url": "https://camp.org/",
        "granularity": "session",
        "parent_verdict": "parent_ready",
    }
    base.update(kw)
    return base


def test_unverified_row_held():
    published, held = apply_publish_gates([_row(parent_verdict="")])
    assert published == []
    assert held[0]["held_reason"] == "unverified"


def test_wrong_audience_verdict_held_with_reason():
    _, held = apply_publish_gates([_row(parent_verdict="wrong_audience")])
    assert held[0]["held_reason"] == "verdict:wrong_audience"


def test_brochure_only_published_with_label():
    published, held = apply_publish_gates([_row(parent_verdict="brochure_only")])
    assert held == []
    assert published[0]["label"] == "brochure_only"
    # parent_ready rows carry no label
    published2, _ = apply_publish_gates([_row()])
    assert published2[0]["label"] == ""


def test_past_dated_session_held():
    _, held = apply_publish_gates([_row(dates="6/22/2024 - 7/2/2024")])
    assert held[0]["held_reason"] == "date_sanity"


def test_dateless_session_held_program_row_published():
    published, held = apply_publish_gates(
        [
            _row(dates=""),
            _row(
                name="Camp Org — Summer Program",
                dates="",
                granularity="program",
                parent_verdict="brochure_only",
            ),
        ]
    )
    assert [r["held_reason"] for r in held] == ["date_sanity"]
    assert [r["name"] for r in published] == ["Camp Org — Summer Program"]


def test_adult_keyword_row_held_unless_parent_ready():
    _, held = apply_publish_gates(
        [_row(name="Adult Pottery Night", parent_verdict="brochure_only")]
    )
    assert held[0]["held_reason"] == "audience_keyword"

    published, _ = apply_publish_gates([_row(name="Dawn Song Summer Bird Walk")])
    # parent_ready overrides the keyword guard
    assert len(published) == 1


def test_parse_date_range():
    assert parse_date_range("July 7-11", 2026) == (date(2026, 7, 7), date(2026, 7, 11))
    assert parse_date_range("6/22-7/2", 2026) == (date(2026, 6, 22), date(2026, 7, 2))
    assert parse_date_range("June 28 - July 2", 2026) == (
        date(2026, 6, 28),
        date(2026, 7, 2),
    )
    assert parse_date_range("['June 17-21', 'June 24-28']", 2026) == (
        date(2026, 6, 17),
        date(2026, 6, 28),
    )
    assert parse_date_range("call for dates", 2026) is None
