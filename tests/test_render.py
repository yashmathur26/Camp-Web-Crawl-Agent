"""roadmap2 Phase 2: render policy, thin-render detection, capture round-trip."""

from __future__ import annotations

import shutil

from config import settings
from src import capture
from src.crawl import fetch_wait_until, is_thin_render
from src.data_layout import DATA_ROOT, town_slug


def test_wait_policy_networkidle_for_js_hosts():
    # JS-render hosts get networkidle even on a plain page fetch (no kind).
    assert fetch_wait_until("https://the-robo-hub.hisawyer.com/schedules") == "networkidle"
    assert fetch_wait_until("https://lexrecma.myrec.com/info/activities") == "networkidle"
    assert fetch_wait_until("https://ymca.daxko.com/programs") == "networkidle"


def test_wait_policy_domcontentloaded_for_static_hosts():
    assert fetch_wait_until("https://lexingtonsymphony.org/jazz") == "domcontentloaded"


def test_wait_policy_register_kind_always_networkidle():
    assert fetch_wait_until("https://lexingtonsymphony.org/jazz", kind="register") == "networkidle"


def test_is_thin_render():
    assert is_thin_render("") is True
    assert is_thin_render("short") is True
    assert is_thin_render("x" * 5000) is False


def test_capture_roundtrip():
    town = "Zz_capture_test"
    original = settings.SETTINGS.get("b5_capture_pages", False)
    settings.SETTINGS["b5_capture_pages"] = True
    url = "https://camp.org/programs/soccer"
    try:
        assert capture.capture_page(town, url, "") is None  # empty not persisted
        path = capture.capture_page(town, url, "Soccer Camp ages 8-12, July 7-11, $425")
        assert path is not None and path.exists()
        loaded = capture.load_capture(town, url)
        assert "Soccer Camp" in loaded
        assert capture.load_capture(town, "https://camp.org/other") is None
    finally:
        settings.SETTINGS["b5_capture_pages"] = original
        shutil.rmtree(DATA_ROOT / town_slug(town), ignore_errors=True)
