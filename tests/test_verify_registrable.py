"""Phase P2: verify_registrable and inline navigator verification."""

import asyncio
from unittest.mock import AsyncMock, patch

from phase_b.camp_navigator import agent_navigate_provider
from phase_b.enrollment_signals import (
    attach_inline_verification,
    verify_registrable,
    verdict_from_signals,
)
from tests.fixture_helpers import load_fixture


def test_verify_registrable_webtrac_fixture():
    url, html, _ = load_fixture("webtrac", "majwhaydenweb.myvscloud.com.iteminfo")
    sig = verify_registrable(url, html)
    assert sig.auto_verdict == "parent_ready"
    assert sig.has_cart_cta
    assert verdict_from_signals(sig, html) == "parent_ready"


def test_verify_registrable_pure_no_session_name():
    """verify_registrable must not depend on session_name (unlike extract_enrollment_signals)."""
    url = "https://ymca.myvscloud.com/webtrac/web/iteminfo.html?FMID=12345"
    html = """
    <h1>Summer Day Camp</h1>
    <p>Ages 8-12. Program fee $425.</p>
    <a href="addtocart.aspx">Add to Cart</a>
    """
    sig = verify_registrable(url, html)
    assert sig.auto_verdict == "parent_ready"


def test_attach_inline_verification_sets_parent_fields():
    url, html, _ = load_fixture("webtrac", "majwhaydenweb.myvscloud.com.iteminfo")
    session = {
        "name": "Summer Camp Week",
        "register_url": url,
        "platform": "webtrac",
    }
    row = attach_inline_verification(session, url, html)
    assert row["parent_verdict"] == "parent_ready"
    assert row["parent_can_register"] is True
    assert "has_cart_cta" in row["enrollment_signals"]


def test_agent_navigator_verifies_register_fetch():
    url, html, _ = load_fixture("webtrac", "majwhaydenweb.myvscloud.com.iteminfo")

    async def _run():
        with patch(
            "phase_b.camp_navigator._pick_agent_urls",
            return_value={
                "catalog_urls": [],
                "register_urls": [{"url": url, "label": "Camp", "why": "register"}],
                "reasoning": "test",
            },
        ):
            with patch(
                "phase_b.platforms._fetch",
                new_callable=AsyncMock,
                return_value=(html, []),
            ):
                with patch(
                    "phase_b.platforms.detect_platform",
                    return_value="custom",
                ):
                    with patch(
                        "phase_b.platforms.adapter_llm",
                        new_callable=AsyncMock,
                        return_value=[
                            {
                                "name": "Summer Camp Week",
                                "register_url": url,
                                "platform": "llm",
                                "kind": "session",
                            }
                        ],
                    ):
                        sessions, _ = await agent_navigate_provider(
                            "https://example.com/camps",
                            "camp page",
                            [],
                        )
        return sessions

    sessions = asyncio.run(_run())
    assert len(sessions) == 1
    assert sessions[0]["parent_verdict"] == "parent_ready"
    assert sessions[0]["parent_can_register"] is True


def test_parent_verify_skips_inline_verified():
    from phase_b.parent_verify import verify_sessions

    url = "https://majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=1"
    sessions = [
        {
            "name": "Already verified",
            "register_url": url,
            "platform": "webtrac",
            "quality_tier": "registrable",
            "parent_verdict": "parent_ready",
            "parent_can_register": True,
            "enrollment_signals": "{}",
            "parent_verify_reason": "inline",
        },
    ]

    async def mock_fetch(u):
        raise AssertionError("should not re-fetch inline-verified session")

    with patch("phase_b.parent_verify._fetch_verify_page", side_effect=mock_fetch):
        with patch("phase_b.parent_verify.is_available", return_value=True):
            out = asyncio.run(verify_sessions(sessions))

    assert out[0]["parent_verdict"] == "parent_ready"
    assert out[0]["parent_can_register"] is True
