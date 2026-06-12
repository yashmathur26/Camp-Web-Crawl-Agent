"""Task 2.2: rendered rescue — budget enforcement + platform re-detection."""

from __future__ import annotations

import asyncio
from pathlib import Path

from config import settings
from src import platforms
from src.platforms import (
    _links_from_html,
    rendered_rescue,
    reset_render_budget,
)

FIXTURES = Path(__file__).parent / "fixtures"
SCHEDULES_HTML = (FIXTURES / "sawyer_schedules.html").read_text(encoding="utf-8")

# Marketing page whose Sawyer embed only exists in (rendered) HTML.
EMBED_PAGE_HTML = """
<html><body>
  <h1>Fuse Lexington Summer Program</h1>
  <a href="https://www.hisawyer.com/the-robo-hub/schedules">Register</a>
  <script src="https://www.hisawyer.com/embed/abc-token.js"></script>
</body></html>
"""


def _patch_fetch(monkeypatch, pages: dict[str, str], calls: list[str]):
    async def fake_fetch_rendered(url, *, wait="networkidle", timeout_s=20):
        calls.append(url)
        for key, html in pages.items():
            if key in url:
                return html
        return None

    import src.crawl as crawl

    monkeypatch.setattr(crawl, "fetch_rendered", fake_fetch_rendered)


def test_rescue_redetects_sawyer_and_routes_to_adapter(monkeypatch):
    reset_render_budget()
    calls: list[str] = []
    _patch_fetch(
        monkeypatch,
        {
            "fuseprogram.com": EMBED_PAGE_HTML,
            "/the-robo-hub/schedules": SCHEDULES_HTML,
        },
        calls,
    )
    sessions, platform = asyncio.run(
        rendered_rescue("https://www.fuseprogram.com/lexington")
    )
    assert platform == "sawyer"
    assert len(sessions) >= 1
    assert all("hisawyer.com" in s["register_url"] for s in sessions)


def test_rescue_extracts_registration_links_without_platform(monkeypatch):
    reset_render_budget()
    html = """
    <html><body>
      <a href="/summer/register-now">Register for Summer Camp</a>
      <a href="/about">About us</a>
    </body></html>
    """
    _patch_fetch(monkeypatch, {"plaincamp.org": html}, [])
    sessions, platform = asyncio.run(rendered_rescue("https://plaincamp.org/"))
    assert platform == "rendered"
    assert len(sessions) == 1
    assert sessions[0]["register_url"] == "https://plaincamp.org/summer/register-now"


def test_budget_per_host_enforced(monkeypatch):
    reset_render_budget()
    calls: list[str] = []
    _patch_fetch(monkeypatch, {"slowhost.org": "<html></html>"}, calls)
    orig = settings.SETTINGS.get("render_max_pages_per_host", 3)
    settings.SETTINGS["render_max_pages_per_host"] = 2
    try:
        for _ in range(4):
            asyncio.run(rendered_rescue("https://slowhost.org/page"))
        assert len(calls) == 2  # 3rd and 4th call blocked by host budget
    finally:
        settings.SETTINGS["render_max_pages_per_host"] = orig


def test_budget_per_town_enforced(monkeypatch):
    reset_render_budget()
    calls: list[str] = []
    _patch_fetch(monkeypatch, {"": "<html></html>"}, calls)
    orig = settings.SETTINGS.get("render_max_pages_per_town", 60)
    settings.SETTINGS["render_max_pages_per_town"] = 3
    try:
        for i in range(6):
            asyncio.run(rendered_rescue(f"https://host{i}.org/"))
        assert len(calls) == 3
    finally:
        settings.SETTINGS["render_max_pages_per_town"] = orig
    reset_render_budget()


def test_links_from_html_absolute_and_deduped():
    links = _links_from_html(
        "https://x.org/a/",
        '<a href="/reg">One</a><a href="/reg">Dup</a><a href="https://y.com/p">Two</a>',
    )
    assert {l["url"] for l in links} == {"https://x.org/reg", "https://y.com/p"}
