"""Tests for parent verify dedupe and rules-first path."""

import asyncio
from unittest.mock import patch

from src.parent_verify import verify_sessions


def test_auto_pass_skips_llm():
    sessions = [
        {
            "name": "Day Camp",
            "register_url": "https://lexrecma.myrec.com/info/activities/program_details.aspx?ProgramID=1",
            "platform": "myrec",
            "source_url": "https://lexrecma.myrec.com",
            "quality_tier": "registrable",
        },
        {
            "name": "Day Camp Copy",
            "register_url": "https://lexrecma.myrec.com/info/activities/program_details.aspx?ProgramID=1",
            "platform": "myrec",
            "source_url": "https://lexrecma.myrec.com",
            "quality_tier": "registrable",
        },
    ]
    html = """
    <a href="#">Register Now</a>
    <p>Summer day camp ages 8-12. $400</p>
    """

    async def mock_fetch(url):
        return html

    with patch("src.parent_verify._fetch_verify_page", side_effect=mock_fetch):
        with patch("src.parent_verify.is_available", return_value=True):
            with patch("src.parent_verify.chat") as mock_chat:
                out = asyncio.run(verify_sessions(sessions))
                mock_chat.assert_not_called()

    assert len(out) == 2
    assert all(r["parent_verdict"] == "parent_ready" for r in out)


def test_fetch_failed():
    sessions = [
        {
            "name": "Camp",
            "register_url": "https://blocked.example.com/camp",
            "platform": "llm",
            "source_url": "https://blocked.example.com",
            "quality_tier": "needs_trail",
        },
    ]

    async def mock_fetch(url):
        return ""

    with patch("src.parent_verify._fetch_verify_page", side_effect=mock_fetch):
        with patch("src.parent_verify.is_available", return_value=False):
            out = asyncio.run(verify_sessions(sessions))

    assert out[0]["parent_verdict"] == "fetch_failed"
