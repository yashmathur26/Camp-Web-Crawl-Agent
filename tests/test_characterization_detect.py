"""Lock detect_platform against real captured provider pages."""

from __future__ import annotations

from src.platforms import COMMUNITY_ED, MYREC, WEBTRAC, detect_platform
from tests.fixture_helpers import load_platform_fixture


def test_detect_webtrac_jwhayden_seed():
    url, html, links = load_platform_fixture("webtrac")
    assert detect_platform(url, links, html) == WEBTRAC


def test_detect_myrec_lexrec_listing():
    url, html, links = load_platform_fixture("myrec")
    assert detect_platform(url, links, html) == MYREC


def test_detect_community_ed_lexplorations_landing():
    url, html, links = load_platform_fixture("community_ed")
    assert detect_platform(url, links, html) == COMMUNITY_ED


def test_detect_generic_summers_edge_marketing_site():
    url, html, links = load_platform_fixture("generic")
    assert detect_platform(url, links, html) == "campbrain"
