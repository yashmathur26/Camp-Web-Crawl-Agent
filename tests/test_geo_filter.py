"""Tests for out-of-state URL filtering."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.geo_filter import is_out_of_state_url  # noqa: E402
from src.validate_search_result import validate_search_result  # noqa: E402


def test_rejects_lexington_kentucky_gov():
    blocked, reason = is_out_of_state_url(
        "https://lexingtonky.gov/playing/camps/summer-camps",
        title="Summer camps | City of Lexington, Kentucky",
    )
    assert blocked
    assert "kentucky" in reason.lower() or "ky" in reason.lower()


def test_keeps_lexington_ma_gov():
    blocked, _ = is_out_of_state_url(
        "https://lexingtonma.gov/2503/Lexrec-Summer-day-Camp",
        title="LexRec Summer day Camp",
    )
    assert not blocked


def test_keeps_worcester_ma_jcc():
    blocked, _ = is_out_of_state_url(
        "https://worcesterjcc.org/summer-camps",
        title="Summer Camps - Worcester JCC",
    )
    assert not blocked


def test_validate_rejects_kentucky_ymca():
    r = validate_search_result(
        {
            "url": "https://ymcacky.org/programs/camps",
            "title": "Camps - YMCA of Central Kentucky",
            "snippet": "Summer day camp",
        }
    )
    assert r.verdict == "reject"
    assert "out of state" in r.reason


def test_rejects_pittsburgh_jcc():
    blocked, reason = is_out_of_state_url(
        "https://jccpgh.org/jcc-camps",
        title="JCC Camps - Jewish Community Center of Greater Pittsburgh",
    )
    assert blocked
    assert "pittsburgh" in reason.lower() or "jccpgh" in reason.lower()


def test_rejects_new_haven_jcc():
    blocked, reason = is_out_of_state_url(
        "https://jccnh.org/daycamps",
        title="JCC Day Camps | JCC of Greater New Haven",
    )
    assert blocked
    assert "new haven" in reason.lower() or "jccnh" in reason.lower()


def test_rejects_national_jcc_index():
    blocked, reason = is_out_of_state_url(
        "https://jcca.org/about-us/all-jcc-camps",
        title="JCCs of North America Day and Overnight Camps",
    )
    assert blocked
    assert "national" in reason.lower()


def test_rejects_aca_blog():
    blocked, _ = is_out_of_state_url(
        "https://acacamps.org/blog/sponsored/how-write-parent-handbook-summer-camps",
        title="How to Write a Parent Handbook for Summer Camps",
    )
    assert blocked


def test_keeps_ymca_boston():
    blocked, _ = is_out_of_state_url(
        "https://ymcaboston.org/youth-and-family/camps/day-camps",
        title="Day Camps - YMCA of Greater Boston",
    )
    assert not blocked


def test_rejects_burlington_vermont():
    blocked, reason = is_out_of_state_url(
        "https://burlingtonvt.gov/1084/Summer-Camps",
        title="Summer Camps | Burlington, VT",
    )
    assert blocked


def test_rejects_burlington_north_carolina():
    blocked, reason = is_out_of_state_url(
        "https://burlingtonnc.gov/1334/Summer-Camps",
        title="Summer Camps | Burlington, NC - Official Website",
    )
    assert blocked


def test_rejects_burlington_new_jersey_myrec():
    blocked, _ = is_out_of_state_url(
        "https://burlingtonnj.myrec.com/info/activities/program_details.aspx?ProgramID=29828",
        title="Summer Camp - City of Burlington Parks and Recreation",
    )
    assert blocked


def test_keeps_burlington_massachusetts():
    blocked, _ = is_out_of_state_url(
        "https://burlington.org/164/Programs-Events",
        title="Programs & Events | Burlington, MA",
    )
    assert not blocked


def test_rejects_state_suffix_gov_hosts():
    blocked, reason = is_out_of_state_url(
        "https://lexingtonky.gov/playing/camps/summer-camps",
        title="Summer camps",
    )
    assert blocked
    assert ".ky.gov" in reason.lower() or "ky" in reason.lower()


def test_rejects_comma_state_texas():
    blocked, reason = is_out_of_state_url(
        "https://example.com/camps",
        title="Summer Camp Programs | Austin, Texas",
    )
    assert blocked
    assert "texas" in reason.lower()


def test_rejects_comma_state_co_abbrev():
    blocked, _ = is_out_of_state_url(
        "https://denvergov.org/recreation",
        title="Youth Camps | Denver, CO",
    )
    assert blocked


def test_keeps_massachusetts_in_title():
    blocked, _ = is_out_of_state_url(
        "https://burlington.org/camps",
        title="Summer Camps | Burlington, Massachusetts",
    )
    assert not blocked


def test_validate_rejects_burlington_vt_search_hit():
    r = validate_search_result(
        {
            "url": "https://burlingtonvt.gov/1084/Summer-Camps",
            "title": "Summer Camps | Burlington, VT",
            "snippet": "Municipal summer camps",
        }
    )
    assert r.verdict == "reject"
    assert "out of state" in r.reason
