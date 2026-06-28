"""Phase 0: junk-audit unit tests + characterization of the frozen v2 baseline.

The characterization tests assert the CURRENT (wrong) output so later phases
can prove they removed it. When Phase 7 cuts over, the `_characterization_*`
assertions flip from "junk is present" to "junk is gone".
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from phase_c.junk_audit import (
    audit_row,
    has_evidence,
    is_chrome_name,
    is_offhost_register,
    is_unusable_name,
)

BASELINE = Path("data/_baseline_v2")


# --- unit: chrome / unusable names ---------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Back to Top",
        "skip to Cookie Notice",
        "Skip to main content",
        "See Details",
        "Register",
        "Register Here",
        "Join Waitlist",
        "Manage Cookies",
        "  back to top.  ",
    ],
)
def test_is_chrome_name_flags_chrome(name):
    assert is_chrome_name(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "Super Soccer Stars",
        "radKids",
        "Lexrec Summer Day Camp",
        "Quickball",
        "Challenger Tiny Tykes Soccer",
    ],
)
def test_is_chrome_name_keeps_real_names(name):
    assert is_chrome_name(name) is False


def test_is_unusable_name_catches_filenames_and_ids():
    assert is_unusable_name("logo-final.png") is True
    assert is_unusable_name("12345") is True
    assert is_unusable_name("Themunroecenterforthearts") is True
    assert is_unusable_name("") is True
    assert is_unusable_name("Art Camp") is False


# --- unit: off-host register & evidence -----------------------------------


def test_offhost_register_flags_unrelated_domain():
    assert is_offhost_register(
        "https://ncbi.nlm.nih.gov/pubmed/26933943",
        "https://massgeneral.org/psychiatry/research/program",
    ) is True


def test_offhost_register_allows_same_domain_and_platforms():
    assert is_offhost_register(
        "https://lexingtonsymphony.org/jazz-program",
        "https://lexingtonsymphony.org/jazz-program",
    ) is False
    # Recognized registration platform on another host is fine (Jotform/WebTrac).
    assert is_offhost_register(
        "https://form.jotform.com/2345", "https://lakeside-camp.org/summer"
    ) is False


def test_has_evidence():
    assert has_evidence({"ages": "8-12"}) is True
    assert has_evidence({"dates": "July 7"}) is True
    assert has_evidence({"price": "$425"}) is True
    assert has_evidence({"name": "Camp", "register_url": "x"}) is False


def test_audit_row_clean_session():
    clean = {
        "name": "Super Soccer Stars",
        "register_url": "https://lakeside-camp.org/register",
        "info_url": "https://lakeside-camp.org/soccer",
        "source_url": "https://lakeside-camp.org/soccer",
        "ages": "3-5",
        "dates": "July 7-11",
        "price": "$200",
    }
    assert audit_row(clean) == []


# --- characterization: the frozen baseline still contains the documented junk -


def _load(town: str) -> list[dict]:
    path = BASELINE / town / "camp_sessions.csv"
    if not path.exists():
        pytest.skip(f"frozen baseline missing: {path}")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_characterization_lexington_has_chrome_name_junk():
    rows = _load("lexington")
    names = {r["name"] for r in rows}
    # roadmap2 §1: these chrome strings were saved as camp names.
    assert "Back to Top" in names
    assert any(n.lower().startswith("skip to") for n in names)
    # And the audit catches them.
    chrome_rows = [r for r in rows if "chrome_name" in audit_row(r)]
    assert len(chrome_rows) >= 4


def test_characterization_massgeneral_offhost_register():
    rows = _load("lexington")
    offhost = [
        r for r in rows if "ncbi.nlm.nih.gov" in (r.get("register_url") or "")
    ]
    assert offhost, "expected the ncbi.nlm.nih.gov register URL in the baseline"
    assert "offhost_register" in audit_row(offhost[0])


def test_characterization_burlington_is_mostly_junk():
    rows = _load("burlington")
    junk = [r for r in rows if audit_row(r)]
    # Documented collapse: every Burlington row is junk in the frozen run.
    assert len(junk) == len(rows)
    assert len(rows) > 0
