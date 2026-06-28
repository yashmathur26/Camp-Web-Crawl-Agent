"""Tests for broad camp discovery + verification."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from phase_a.camp_discovery import (  # noqa: E402
    collect_camp_candidate_links,
    score_camp_candidate,
)


def test_scores_viking_program_links():
    assert score_camp_candidate(
        "https://vikingcamps.com/program/summer-week-08-soccer-academy",
        "Soccer Academy",
    ) >= 2
    assert score_camp_candidate(
        "https://vikingcamps.com/program/flag-football-camp",
        "Flag Football Camp",
    ) >= 2


def test_scores_belmont_summer_paths():
    assert score_camp_candidate(
        "https://belmonthill.org/about/summer-programs/sport-camps",
        "Sport Camps",
    ) >= 4


def test_collects_same_host_camp_links():
    seed = "https://vikingcamps.com/summer"
    links = [
        {"url": "https://vikingcamps.com/program/soccer-camp", "text": "Soccer Camp"},
        {"url": "https://vikingcamps.com/about", "text": "About Us"},
        {"url": "https://vikingcamps.com/program/basketball-camp", "text": "Basketball"},
    ]
    out = collect_camp_candidate_links(seed, links)
    urls = {x["url"] for x in out}
    assert "https://vikingcamps.com/program/soccer-camp" in urls
    assert "https://vikingcamps.com/about" not in urls


def test_rejects_swim_test_noise():
    assert score_camp_candidate(
        "https://ymca.org/swim-test",
        "FREE PRE-CAMP SWIM TESTS",
    ) <= 0
