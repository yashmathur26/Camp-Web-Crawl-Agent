"""Lock structured adapter output against real captured HTML fixtures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.platforms import adapter_community_ed, adapter_myrec, adapter_webtrac
from tests.conftest_characterization import patch_offline_fetch
from tests.fixture_helpers import load_platform_fixture

LOCKS = json.loads((Path(__file__).parent / "characterization_locks.json").read_text(encoding="utf-8"))


def test_adapter_webtrac_session_count_and_register_urls():
    """Regression: WebTrac must keep yielding 20 sessions from saved Hayden catalog HTML."""
    url, html, links = load_platform_fixture("webtrac")
    with patch_offline_fetch():
        sessions = asyncio.run(adapter_webtrac(url, links, html))
    assert len(sessions) == LOCKS["webtrac_session_count"] == 20
    found = sorted({s["register_url"] for s in sessions})
    assert found == LOCKS["webtrac_register_urls"]


def test_adapter_myrec_session_count_and_program_ids():
    """Regression: MyRec must keep yielding 89 programs from saved LexRec listing HTML."""
    url, html, links = load_platform_fixture("myrec")
    with patch_offline_fetch():
        sessions = asyncio.run(adapter_myrec(url, links, html))
    assert len(sessions) == LOCKS["myrec_session_count"] == 89
    pids = {s["register_url"].split("ProgramID=")[-1].split("#")[0].split("&")[0] for s in sessions}
    assert sorted(pids) == LOCKS["myrec_program_ids"]


def test_adapter_community_ed_from_crawl_path_fixture():
    """BASELINE: crawl-path Lexplorations landing yields 0 products (sparse rendered HTML)."""
    url, html, links = load_platform_fixture("community_ed")
    with patch_offline_fetch():
        sessions = asyncio.run(adapter_community_ed(url, links, html))
    assert len(sessions) == LOCKS["community_ed_session_count"] == 0
