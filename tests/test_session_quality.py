"""Tests for session quality tier classification."""

from src.session_quality import classify_session_tier


def test_myrec_registrable():
    tier, _ = classify_session_tier(
        {
            "name": "Summer Day Camp",
            "register_url": "https://lexrecma.myrec.com/info/activities/program_details.aspx?ProgramID=30941",
            "platform": "myrec",
            "source_url": "https://lexrecma.myrec.com",
        }
    )
    assert tier == "registrable"


def test_teens_hub_rejected():
    tier, reason = classify_session_tier(
        {
            "name": "Teens",
            "register_url": "https://bostonjcc.org/program/teens",
            "platform": "woocommerce",
            "source_url": "https://bostonjcc.org",
        }
    )
    assert tier == "rejected"
    assert "hub" in reason.lower()


def test_ky_geo_rejected():
    tier, _ = classify_session_tier(
        {
            "name": "YMCA Camp",
            "register_url": "https://lexingtonymca.com/programs",
            "platform": "llm",
            "source_url": "https://lexingtonymca.com",
        }
    )
    assert tier == "rejected"
