"""Tests for parent auditor hole detection."""

from src.parent_auditor import _rule_based_holes


def test_missing_category_hole():
    sessions = [
        {
            "name": "Soccer Camp",
            "register_url": "https://x.myrec.com/program_details.aspx?ProgramID=1",
            "parent_verdict": "parent_ready",
            "platform": "myrec",
        }
    ]
    holes = _rule_based_holes("Lexington", sessions, known_hosts=set())
    types = {h["type"] for h in holes}
    assert "missing_category" in types


def test_brochure_gap_hole():
    sessions = [
        {
            "name": "Camp A",
            "register_url": "https://ymca.example.com/camp-a",
            "parent_verdict": "brochure_only",
            "source_url": "https://ymca.example.com",
        },
        {
            "name": "Camp B",
            "register_url": "https://ymca.example.com/camp-b",
            "parent_verdict": "brochure_only",
            "source_url": "https://ymca.example.com",
        },
    ]
    holes = _rule_based_holes("Lexington", sessions, known_hosts={"ymca.example.com"})
    assert any(h["type"] == "brochure_gap" for h in holes)
