"""Lock enrollment_signals on real captured register/detail pages."""

from __future__ import annotations

import json
from pathlib import Path

from src.enrollment_signals import extract_enrollment_signals
from tests.fixture_helpers import load_fixture

LOCKS = json.loads((Path(__file__).parent / "characterization_locks.json").read_text(encoding="utf-8"))


def test_webtrac_iteminfo_page_verdict():
    url, html, _ = load_fixture("webtrac", "majwhaydenweb.myvscloud.com.iteminfo")
    sig = extract_enrollment_signals(url, html, session_name="Summer Camp Week")
    assert sig.auto_verdict == LOCKS["signals"]["webtrac_iteminfo"] == "parent_ready"


def test_myrec_program_detail_page_verdict():
    url, html, _ = load_fixture("myrec", "lexrecma.myrec.com.program_detail")
    sig = extract_enrollment_signals(url, html, session_name="LexRec Day Camp")
    assert sig.auto_verdict == LOCKS["signals"]["myrec_program_detail"] == "brochure_only"
