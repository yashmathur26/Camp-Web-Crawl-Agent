"""Tests for search result validation."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.validate_search_result import validate_search_result  # noqa: E402


def test_rejects_aggregator():
    r = validate_search_result(
        {
            "url": "https://www.care.com/summer-camps/boston",
            "title": "Summer Camps in Boston",
            "snippet": "Find camps",
        }
    )
    assert r.verdict == "reject"
    assert r.source_type == "aggregator"


def test_keeps_guide_for_outbound_mining():
    # activityhero.com is in GUIDE_DOMAINS: kept so its outbound links are mined.
    r = validate_search_result(
        {
            "url": "https://www.activityhero.com/camps/boston",
            "title": "Summer Camps in Boston",
            "snippet": "Find camps",
        }
    )
    assert r.verdict == "keep"
    assert r.source_type == "guide"


def test_rejects_after_school():
    r = validate_search_result(
        {
            "url": "https://example.com/after-school-guide",
            "title": "After School Guide for Parents",
            "snippet": "Programs list",
        }
    )
    assert r.verdict == "reject"
    assert r.source_type == "after_school"


def test_keeps_community_ed():
    r = validate_search_result(
        {
            "url": "https://lexingtoncommunityed.org/childrens-programs/",
            "title": "Children's Summer Programs 2026",
            "snippet": "Community education summer programs",
        }
    )
    assert r.verdict == "keep"
    assert r.preferred is True


def test_keeps_myrec():
    r = validate_search_result(
        {
            "url": "https://actonma.myrec.com/info/activities",
            "title": "Summer Camp Registration",
            "snippet": "Parks and recreation",
        }
    )
    assert r.verdict == "keep"
    assert r.preferred is True


if __name__ == "__main__":
    test_rejects_aggregator()
    test_rejects_after_school()
    test_keeps_community_ed()
    test_keeps_myrec()
    print("All validation tests passed.")
