"""Lock enumerate_provider end-to-end on real fixtures (fetch mocked only)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from phase_b.platforms import enumerate_provider
from tests.conftest_characterization import patch_offline_fetch
from tests.fixture_helpers import load_platform_fixture

LOCKS = json.loads((Path(__file__).parent / "characterization_locks.json").read_text(encoding="utf-8"))


def test_enumerate_provider_webtrac_seed():
    url, _, _ = load_platform_fixture("webtrac")
    with patch_offline_fetch():
        result = asyncio.run(enumerate_provider(url, town_hint="Lexington"))
    # Re-measured 2026-06-10: 40 after Specialty Camps fixture added (matches Lexington baseline).
    assert len(result["sessions"]) == LOCKS["enumerate_webtrac_session_count"] == 40
    assert result["platform"] == "webtrac"


def test_enumerate_provider_generic_marketing_site():
    url, _, _ = load_platform_fixture("generic")
    with patch_offline_fetch():
        result = asyncio.run(enumerate_provider(url, town_hint="Burlington"))
    assert len(result["sessions"]) == LOCKS["enumerate_generic_session_count"] == 1
    assert result["platform"].startswith("campbrain")
