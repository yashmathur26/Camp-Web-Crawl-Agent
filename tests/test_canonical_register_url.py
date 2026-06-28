"""Task 4.1: canonical_register_url + platform-ID dedupe in write outputs."""

from __future__ import annotations

import csv
import shutil
from urllib.parse import parse_qs, urlparse

from config import settings
from shared.data_layout import DATA_ROOT, town_slug
from phase_b.platforms import make_session
from phase_b.sessions import _dedupe_published_rows, write_session_outputs
from shared.urls import canonical_register_url, register_platform_id

TOWN = "Zz_canon_test"


def teardown_module(_module=None):
    shutil.rmtree(DATA_ROOT / town_slug(TOWN), ignore_errors=True)


def test_webtrac_iteminfo_keeps_only_fmid_module():
    url = (
        "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html"
        "?Module=AR&FMID=12345&InterfaceParameter=WebTrac&_csrf_token=abc123"
    )
    canon = canonical_register_url(url, "webtrac")
    qs = parse_qs(urlparse(canon).query)
    assert set(qs) == {"FMID", "Module"}
    assert qs["FMID"] == ["12345"]


def test_webtrac_search_strips_csrf_and_arwebsearch():
    url = (
        "https://majwhaydenweb.myvscloud.com/webtrac/web/search.html"
        "?module=AR&type=CAMP&_csrf_token=zzz&ARWebSearch_Category=Sports"
    )
    canon = canonical_register_url(url, "webtrac")
    qs = parse_qs(urlparse(canon).query)
    assert "_csrf_token" not in qs
    assert not any(k.lower().startswith("arwebsearch") for k in qs)
    assert qs["type"] == ["CAMP"]


def test_myrec_keeps_only_programid():
    url = (
        "https://lexrecma.myrec.com/info/activities/program_details.aspx"
        "?ProgramID=30941&type=camps&utm_source=newsletter"
    )
    canon = canonical_register_url(url, "myrec")
    qs = parse_qs(urlparse(canon).query)
    assert set(qs) == {"ProgramID"}


def test_tracking_params_stripped_everywhere():
    url = "https://camp.org/register?id=5&utm_campaign=x&fbclid=y&PHPSESSID=z&sid=1"
    canon = canonical_register_url(url)
    qs = parse_qs(urlparse(canon).query)
    assert set(qs) == {"id"}


def test_register_platform_id():
    fmid = canonical_register_url(
        "https://x.myvscloud.com/webtrac/web/iteminfo.html?Module=AR&FMID=99"
    )
    pid = canonical_register_url(
        "https://t.myrec.com/info/activities/program_details.aspx?ProgramID=7"
    )
    assert register_platform_id(fmid) == "x.myvscloud.com|fmid|99"
    assert register_platform_id(pid) == "t.myrec.com|programid|7"
    assert register_platform_id("https://camp.org/register?id=5") == ""


def test_fmid_equal_rows_dedupe_to_one():
    a = make_session(
        "Specialty Camp: Chess",
        "https://x.myvscloud.com/webtrac/web/iteminfo.html?Module=AR&FMID=99&_csrf_token=aaa",
        platform="webtrac",
        dates="July 7",
    )
    b = make_session(
        "Chess Camp",
        "https://x.myvscloud.com/webtrac/web/iteminfo.html?FMID=99&Module=AR&InterfaceParameter=Web",
        platform="webtrac",
        dates="July 7",
    )
    out = _dedupe_published_rows([a, b])
    assert len(out) == 1


def test_host_name_dates_dedupe_keeps_higher_tier():
    weak = make_session(
        "Robotics Camp",
        "https://camp.org/info",  # not a platform URL -> needs_trail
        platform="custom",
        dates="July 7",
        source_url="https://camp.org/",
    )
    strong = make_session(
        "Robotics Camp 2026",  # same norm_name after token stripping
        "https://camp.org/register?id=5",  # /register -> registrable
        platform="custom",
        dates="July 7",
        source_url="https://camp.org/",
    )
    out = _dedupe_published_rows([weak, strong])
    assert len(out) == 1
    assert out[0]["register_url"].endswith("/register?id=5")


def test_write_outputs_canonicalizes_and_dedupes(tmp_path):
    a = make_session(
        "Art Camp",
        "https://t.myrec.com/info/activities/program_details.aspx?ProgramID=7&utm_source=x",
        platform="myrec",
        dates="July 7",
    )
    b = make_session(
        "Art Camp (Session 2 link dup)",
        "https://t.myrec.com/info/activities/program_details.aspx?ProgramID=7&type=camps",
        platform="myrec",
        dates="July 7",
    )
    results = [{"url": "https://t.myrec.com", "platform": "myrec", "sessions": [a, b]}]
    orig = settings.SETTINGS.get("b5_validation_gate", True)
    settings.SETTINGS["b5_validation_gate"] = True
    try:
        csv_path, _txt, total = write_session_outputs(TOWN, results)
        assert total == 1
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        qs = parse_qs(urlparse(rows[0]["register_url"]).query)
        assert set(qs) == {"ProgramID"}
    finally:
        settings.SETTINGS["b5_validation_gate"] = orig
