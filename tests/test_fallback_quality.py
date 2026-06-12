"""Task 1.3: provider-level program rows flow through quality phases."""

from __future__ import annotations

from src.parent_verify import _floor_program_verdict
from src.session_quality import classify_session_tier
from src.sessions import _fallback_program_row


def _program_row(register_url: str) -> dict:
    row = _fallback_program_row(
        "https://vikingcamps.com/lexington",
        {"platform": "custom", "links": []},
    )
    row["register_url"] = register_url
    return row


def test_program_row_with_platform_register_url_is_registrable():
    row = _program_row(
        "https://lexrecma.myrec.com/info/activities/program_details.aspx?ProgramID=123"
    )
    tier, reason = classify_session_tier(row)
    assert tier == "registrable"


def test_program_row_with_marketing_url_needs_trail():
    row = _program_row("https://vikingcamps.com/lexington")
    tier, reason = classify_session_tier(row)
    assert tier == "needs_trail"
    assert "program" in reason


def test_program_row_never_rejected_for_missing_dates():
    row = _program_row("https://vikingcamps.com/summer")
    assert row["dates"] == "" and row["ages"] == "" and row["price"] == ""
    tier, _ = classify_session_tier(row)
    assert tier != "rejected"


def test_program_row_still_rejected_for_geo_junk():
    # The exemption is for thin metadata only — junk URLs still reject.
    row = _program_row("https://vikingcamps.com/files/brochure.pdf")
    tier, _ = classify_session_tier(row)
    assert tier == "rejected"


def test_floor_program_verdict_not_below_brochure_only():
    program = {"granularity": "program"}
    session = {"granularity": "session"}
    assert _floor_program_verdict(program, "unverified") == "brochure_only"
    assert _floor_program_verdict(program, "wrong_audience") == "wrong_audience"
    assert _floor_program_verdict(program, "parent_ready") == "parent_ready"
    assert _floor_program_verdict(session, "unverified") == "unverified"
