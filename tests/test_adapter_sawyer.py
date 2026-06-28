"""Task 2.1: Sawyer adapter — slug discovery + schedules page parsing.

Fixtures (captured live 2026-06-12):
  sawyer_schedules.html      hisawyer.com/the-robo-hub/schedules (rendered)
  sawyer/fuse_embed.js       hisawyer.com/embed/<token>.js for fuseprogram.com
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from phase_b.platforms import (
    _parse_sawyer_schedules,
    _sawyer_slug_candidates,
    adapter_sawyer,
)

FIXTURES = Path(__file__).parent / "fixtures"
SCHEDULES_HTML = (FIXTURES / "sawyer_schedules.html").read_text(encoding="utf-8")
EMBED_JS = (FIXTURES / "sawyer" / "fuse_embed.js").read_text(encoding="utf-8")


def test_parse_schedules_fixture_yields_sessions():
    sessions = _parse_sawyer_schedules(
        SCHEDULES_HTML, "the-robo-hub", "https://therobohub.com/"
    )
    assert len(sessions) >= 1
    for s in sessions:
        assert s["name"]
        assert "hisawyer.com" in s["register_url"]
        assert "/the-robo-hub/" in s["register_url"]
        assert s["platform"] == "sawyer"


def test_parse_extracts_metadata():
    sessions = _parse_sawyer_schedules(
        SCHEDULES_HTML, "the-robo-hub", "https://therobohub.com/"
    )
    assert any(s["dates"] for s in sessions)
    assert any(s["ages"] for s in sessions)
    assert any(s["price"] for s in sessions)


def test_slug_candidates_from_links_and_embed_js():
    slugs, tokens = _sawyer_slug_candidates(
        "",
        [{"url": "https://www.hisawyer.com/the-robo-hub/schedules?x=1", "text": ""}],
    )
    assert slugs == ["the-robo-hub"]

    # fuse: page only carries an embed token; the JS bundle names the slug
    slugs2, tokens2 = _sawyer_slug_candidates(
        '<script src="https://www.hisawyer.com/embed/e1vc9cXdfZnEq55RP9RqqWR4ivHP-wmo.js"></script>',
        [],
    )
    assert slugs2 == [] and tokens2 == ["e1vc9cXdfZnEq55RP9RqqWR4ivHP-wmo"]
    slugs3, _ = _sawyer_slug_candidates(EMBED_JS, [])
    assert "fuse-school-program" in slugs3


def test_marketplace_slug_excluded():
    slugs, _ = _sawyer_slug_candidates(
        "https://www.hisawyer.com/marketplace/activity-set/99", []
    )
    assert slugs == []


def test_adapter_sawyer_with_mocked_fetch(monkeypatch):
    calls = []

    async def fake_fetch_rendered(url, *, wait="networkidle", timeout_s=20):
        calls.append(url)
        if url.endswith("/the-robo-hub/schedules"):
            return SCHEDULES_HTML
        return None

    import phase_b.crawl as crawl

    monkeypatch.setattr(crawl, "fetch_rendered", fake_fetch_rendered)
    sessions = asyncio.run(
        adapter_sawyer(
            "https://therobohub.com/",
            [{"url": "https://www.hisawyer.com/the-robo-hub/schedules", "text": "Register"}],
            "",
        )
    )
    assert len(sessions) >= 1
    assert all("hisawyer.com" in s["register_url"] for s in sessions)
    assert any(u.endswith("/the-robo-hub/schedules") for u in calls)


def test_adapter_sawyer_no_slug_returns_empty(monkeypatch):
    async def fake_fetch_rendered(url, *, wait="networkidle", timeout_s=20):
        return "<html><body>plain marketing page</body></html>"

    import phase_b.crawl as crawl

    monkeypatch.setattr(crawl, "fetch_rendered", fake_fetch_rendered)
    sessions = asyncio.run(adapter_sawyer("https://example.com/", [], ""))
    assert sessions == []
