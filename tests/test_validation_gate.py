"""roadmap2 Phase 5: validate_session gate + quarantine on write."""

from __future__ import annotations

import csv
import shutil

from config import settings
from src.data_layout import DATA_ROOT, camp_sessions_csv, town_slug
from src.junk_audit import validate_session
from src.platforms import make_session
from src.sessions import write_session_outputs


def test_validate_session_passes_clean_row():
    s = make_session(
        "Super Soccer Stars",
        "https://lexrecma.myrec.com/programs/program_details.aspx?id=9",
        info_url="https://lexrecma.myrec.com/programs/program_details.aspx?id=9",
        ages="3-5",
        dates="July 7-11",
    )
    ok, reasons = validate_session(s)
    assert ok is True and reasons == []


def test_validate_session_quarantines_chrome_and_offhost():
    # Raw chrome name (e.g. name integrity flag off) is caught by the gate.
    chrome = {
        "name": "Back to Top",
        "register_url": "https://x.org/p",
        "info_url": "https://x.org/p",
        "dates": "July 1",
    }
    ok, reasons = validate_session(chrome)
    assert ok is False and "chrome_name" in reasons

    offhost = {
        "name": "Cardiac Program",
        "register_url": "https://ncbi.nlm.nih.gov/pubmed/26933943",
        "info_url": "https://massgeneral.org/psychiatry/research/program",
        "dates": "June 20",
    }
    ok2, reasons2 = validate_session(offhost)
    assert ok2 is False
    assert "offhost_register" in reasons2 or "off_topic" in reasons2


def test_write_outputs_quarantines_junk_rows():
    town = "Zz_gate_test"
    good = make_session(
        "Art Camp",
        "https://camp.org/register",
        info_url="https://camp.org/art",
        ages="6-12",
        dates="July 7",
    )
    junk_chrome = make_session("Back to Top", "https://camp.org/x", dates="July 1")
    junk_noevidence = make_session("Mystery Program", "https://camp.org/y")
    results = [
        {"url": "https://camp.org", "platform": "navigator", "sessions": [good, junk_chrome, junk_noevidence]}
    ]
    orig = settings.SETTINGS.get("b5_validation_gate", True)
    settings.SETTINGS["b5_validation_gate"] = True
    try:
        csv_path, _txt, total = write_session_outputs(town, results)
        assert total == 1  # only the clean row published
        with open(csv_path, newline="", encoding="utf-8") as f:
            published = list(csv.DictReader(f))
        assert [r["name"] for r in published] == ["Art Camp"]

        qpath = csv_path.with_name("camp_sessions_quarantine.csv")
        assert qpath.exists()
        with open(qpath, newline="", encoding="utf-8") as f:
            quarantined = list(csv.DictReader(f))
        reasons = " ".join(r["_quarantine_reason"] for r in quarantined)
        # Phase 1 blanked the chrome name to "" before write -> unusable_name.
        assert "unusable_name" in reasons
        assert "no_evidence" in reasons
        assert len(quarantined) == 2
    finally:
        settings.SETTINGS["b5_validation_gate"] = orig
        shutil.rmtree(DATA_ROOT / town_slug(town), ignore_errors=True)
