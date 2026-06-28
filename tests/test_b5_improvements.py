"""Tests for B.5 quality fixes (Daxko drill-down, provider blocklist, catalog_grid focus)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from phase_b.platforms import _extract_daxko_sessions, _is_catalog_grid_item  # noqa: E402
from phase_a.relevance import classify_session  # noqa: E402
from phase_b.sessions import _filter_b5_providers  # noqa: E402


def test_filter_b5_providers_blocks_gmail_share():
    urls = [
        "https://mail.google.com/mail/u/0?view=cm",
        "https://cedarland.net/summer-camp",
    ]
    kept = _filter_b5_providers(urls)
    assert kept == ["https://cedarland.net/summer-camp"]


def test_catalog_grid_requires_summer_or_camp_signal():
    keep, _ = classify_session(
        "Elementary (K-2)",
        register_url="https://mathschool.com/programs/elementary",
        platform="catalog_grid",
    )
    assert not keep
    keep2, reason2 = classify_session(
        "Summer Coding Camp",
        register_url="https://idtech.com/courses/coding-101-camp",
        platform="catalog_grid",
    )
    assert keep2
    assert reason2 == "youth-summer"


def test_daxko_extract_skips_swim_tests():
    links = [
        {
            "url": "https://operations.daxko.com/Online/5104/ProgramsV2/ProgramDetail.mvc?program_id=1",
            "text": "2026 BOROUGHS FREE PRE-CAMP SWIM TESTS",
        },
        {
            "url": "https://operations.daxko.com/Online/5104/ProgramsV2/ProgramDetail.mvc?program_id=2",
            "text": "2026 Boroughs Summer Camp Ages 5/6",
        },
    ]
    sessions = _extract_daxko_sessions(links, "https://ymcaofcm.org/camp-boroughs")
    assert len(sessions) == 1
    assert "Summer Camp" in sessions[0]["name"]


def test_nested_health_programs_not_catalog_grid():
    assert not _is_catalog_grid_item(
        "https://example.com/",
        {"url": "https://example.com/health/programs/wellness", "text": "Wellness"},
    )
