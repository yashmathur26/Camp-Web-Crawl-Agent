"""roadmap2 Phase 1: make_session never publishes chrome/unusable names."""

from __future__ import annotations

import pytest

from config import settings
from src.platforms import make_session


@pytest.mark.parametrize(
    "chrome",
    ["Back to Top", "See Details", "Skip to main content", "Join Waitlist", "Register"],
)
def test_make_session_blanks_chrome_name(chrome):
    s = make_session(chrome, "https://camp.org/p", info_url="https://camp.org/p")
    assert s["name"] == ""
    assert s["name_status"] == "needs_name"
    assert s["raw_name"] == chrome  # preserved for debugging, not published


@pytest.mark.parametrize(
    "real",
    ["Super Soccer Stars", "radKids", "Lexrec Summer Day Camp", "Quickball"],
)
def test_make_session_keeps_real_name(real):
    s = make_session(real, "https://camp.org/p")
    assert s["name"] == real
    assert s["name_status"] == "ok"
    assert s["raw_name"] == ""


def test_make_session_records_name_source():
    s = make_session("Art Camp", "https://camp.org/p", name_source="title")
    assert s["name_source"] == "title"


def test_name_integrity_flag_off_preserves_legacy_behavior():
    original = settings.SETTINGS.get("b5_name_integrity", True)
    settings.SETTINGS["b5_name_integrity"] = False
    try:
        s = make_session("Back to Top", "https://camp.org/p")
        assert s["name"] == "Back to Top"  # legacy: chrome passes through
        assert s["name_status"] == "ok"
    finally:
        settings.SETTINGS["b5_name_integrity"] = original
