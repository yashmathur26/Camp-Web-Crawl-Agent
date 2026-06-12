"""Task 1.2: provider-level fallback rows for known camp providers."""

from __future__ import annotations

import csv
import shutil

from config import settings
from src.data_layout import DATA_ROOT, town_slug
from src.platforms import make_session
from src.sessions import (
    _best_register_url,
    _fallback_program_row,
    _provider_display_name,
    apply_provider_fallbacks,
    write_session_outputs,
)

TOWN = "Zz_fallback_test"
KNOWN = {"vikingcamps.com"}


def teardown_module(_module=None):
    shutil.rmtree(DATA_ROOT / town_slug(TOWN), ignore_errors=True)


def test_zero_session_known_provider_gets_one_program_row():
    results = [
        {
            "url": "https://www.vikingcamps.com/lexington",
            "platform": "custom",
            "sessions": [],
            "dropped": [],
            "links": [],
        }
    ]
    out = apply_provider_fallbacks(results, TOWN, known_hosts=KNOWN)
    rows = out[0]["sessions"]
    assert len(rows) == 1
    row = rows[0]
    assert row["granularity"] == "program"
    # no better link harvested -> register_url falls back to the seed
    assert row["register_url"] == "https://www.vikingcamps.com/lexington"
    assert row["name"] == "Vikingcamps — Summer Program"
    assert row["platform"] == "custom"


def test_zero_session_unknown_host_stays_empty():
    results = [
        {
            "url": "https://randomflorist.example.com/",
            "platform": "custom",
            "sessions": [],
            "dropped": [],
            "links": [],
        }
    ]
    out = apply_provider_fallbacks(results, TOWN, known_hosts=KNOWN)
    assert out[0]["sessions"] == []


def test_best_register_url_prefers_platform_then_registerish_path():
    seed = "https://vikingcamps.com/"
    result = {
        "links": [
            {"url": "https://vikingcamps.com/about", "text": "About"},
            {"url": "https://vikingcamps.com/register-now", "text": "Register"},
        ]
    }
    assert _best_register_url(result, seed) == "https://vikingcamps.com/register-now"

    result_platform = {
        "links": [
            {"url": "https://vikingcamps.com/about", "text": "About"},
            {
                "url": "https://campscui.active.com/orgs/viking",
                "text": "Sign up",
            },
        ]
    }
    assert (
        _best_register_url(result_platform, seed)
        == "https://campscui.active.com/orgs/viking"
    )


def test_provider_display_name_prefers_title():
    assert (
        _provider_display_name("https://vikingcamps.com/", {"title": "Viking Sports Camps | Lexington MA"})
        == "Viking Sports Camps"
    )
    # www. stripped, TLD dropped, title-cased
    assert _provider_display_name("https://www.goddardschool.com/x", {}) == "Goddardschool"


def test_stale_program_row_dropped_when_host_has_real_sessions():
    real = make_session(
        "Viking Soccer Week 1",
        "https://vikingcamps.com/register/week1",
        dates="July 7-11",
        source_url="https://vikingcamps.com/lexington",
    )
    stale = _fallback_program_row(
        "https://vikingcamps.com/lexington",
        {"platform": "custom", "links": []},
    )
    results = [
        {
            "url": "https://vikingcamps.com/lexington",
            "platform": "custom",
            "sessions": [real, stale],
        }
    ]
    orig = settings.SETTINGS.get("b5_validation_gate", True)
    settings.SETTINGS["b5_validation_gate"] = True
    try:
        csv_path, _txt, total = write_session_outputs(TOWN, results)
        assert total == 1
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert [r["name"] for r in rows] == ["Viking Soccer Week 1"]
    finally:
        settings.SETTINGS["b5_validation_gate"] = orig


def test_program_row_survives_validation_gate():
    # has no dates/ages/price — must NOT be quarantined for no_evidence.
    row = _fallback_program_row(
        "https://vikingcamps.com/lexington",
        {"platform": "custom", "links": []},
    )
    results = [
        {"url": "https://vikingcamps.com/lexington", "platform": "custom", "sessions": [row]}
    ]
    orig = settings.SETTINGS.get("b5_validation_gate", True)
    settings.SETTINGS["b5_validation_gate"] = True
    try:
        csv_path, _txt, total = write_session_outputs(TOWN, results)
        assert total == 1
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["granularity"] == "program"
    finally:
        settings.SETTINGS["b5_validation_gate"] = orig
