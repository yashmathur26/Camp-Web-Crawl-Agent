"""Lock structured adapter output against real captured HTML fixtures.

Fixture lock reconciliation (Phase 1 close-out, 2026-06-10)
------------------------------------------------------------
MyRec (lock: 89 program_details URLs)
  The listing fixture (lexrecma.myrec.com.meta.json) is the full year-round
  activities.aspx catalog: adult fitness (Tai Chi, Pilates, Senior Bingo),
  senior trips/lunches, spring leagues, donations, and youth summer camps.
  Inspected link texts: ~47 adult/senior, ~28 youth/summer, ~14 other.
  Live Lexington baseline keeps 24 MyRec sessions after enumerate_provider's
  youth/summer focus filter — all 24 baseline PIDs are a subset of this 89.
  # BASELINE: whole-catalog count, NOT summer-only; expected to drop to ~24
  after youth/summer filtering in a later phase — not a regression.

WebTrac (lock: 40 iteminfo URLs)
  adapter_webtrac unions up to 5 camp catalogs. The jwhayden.org seed links
  two: module=AR&type=CAMP (20 sessions) and category=Specialty+Camps (20 more).
  Re-captured tests/fixtures/webtrac/majwhaydenweb.myvscloud.com.catalog_specialty
  on 2026-06-10; offline fetch routes specialty vs main catalog separately.
  Count matches data/_baseline/lexington jwhayden.org (40 sessions).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from phase_b.platforms import adapter_community_ed, adapter_myrec, adapter_webtrac
from tests.conftest_characterization import patch_offline_fetch
from tests.fixture_helpers import load_platform_fixture

LOCKS = json.loads((Path(__file__).parent / "characterization_locks.json").read_text(encoding="utf-8"))


def test_adapter_webtrac_session_count_and_register_urls():
    """Regression: WebTrac unions main + Specialty Camps catalogs (40 sessions offline)."""
    url, html, links = load_platform_fixture("webtrac")
    with patch_offline_fetch():
        sessions = asyncio.run(adapter_webtrac(url, links, html))
    # Re-measured 2026-06-10: 20 (type=CAMP) + 20 (Specialty Camps) = 40; matches Lexington baseline.
    assert len(sessions) == LOCKS["webtrac_session_count"] == 40
    found = sorted({s["register_url"] for s in sessions})
    assert found == LOCKS["webtrac_register_urls"]
    assert all(s.get("info_url") == s["register_url"] for s in sessions)


def test_adapter_myrec_session_count_and_program_ids():
    """Regression: MyRec yields every program_details link on the saved listing HTML."""
    url, html, links = load_platform_fixture("myrec")
    with patch_offline_fetch():
        sessions = asyncio.run(adapter_myrec(url, links, html))
    # BASELINE: whole-catalog count, NOT summer-only; expected to drop to ~24 after youth/summer filtering.
    assert len(sessions) == LOCKS["myrec_session_count"] == 89
    pids = {s["register_url"].split("ProgramID=")[-1].split("#")[0].split("&")[0] for s in sessions}
    assert sorted(pids) == LOCKS["myrec_program_ids"]
    assert all(s.get("info_url") == s["register_url"] for s in sessions)


# (deleted per engine-v3 task 4.2 / R1.3: it locked broken behavior — the old
# adapter yielding 0 Lexplorations products was the bug, not the contract.)
