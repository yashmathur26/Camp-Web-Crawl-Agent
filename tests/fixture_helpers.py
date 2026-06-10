"""Load real captured HTML fixtures for characterization tests."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"

SEED_FIXTURE: dict[str, str] = {
    "webtrac": "jwhayden.org",
    "myrec": "lexrecma.myrec.com",
    "community_ed": "lexingtoncommunityed.org",
    "generic": "summersedgedaycamp.com",
}

WEBTRAC_CATALOG_SLUG = "majwhaydenweb.myvscloud.com.catalog"
WEBTRAC_SPECIALTY_CATALOG_SLUG = "majwhaydenweb.myvscloud.com.catalog_specialty"
WEBTRAC_ITEMINFO_SLUG = "majwhaydenweb.myvscloud.com.iteminfo"
MYREC_PROGRAM_SLUG = "lexrecma.myrec.com.program_detail"


def load_fixture(platform: str, slug: str) -> tuple[str, str, list[dict]]:
    """Load (url, html, links) for tests/fixtures/<platform>/<slug>.html."""
    html_path = FIXTURES_ROOT / platform / f"{slug}.html"
    meta_path = FIXTURES_ROOT / platform / f"{slug}.meta.json"
    html = html_path.read_text(encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return meta["url"], html, meta.get("links", [])


def load_platform_fixture(platform: str, slug: str | None = None) -> tuple[str, str, list[dict]]:
    return load_fixture(platform, slug or SEED_FIXTURE[platform])


def _host_slug(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host.replace(":", "_")


def _as_fetch(url: str) -> tuple[str, list[dict]]:
    _, html, links = _resolve_fixture(url)
    return html, links


def _resolve_fixture(url: str) -> tuple[str, str, list[dict]]:
    low = url.lower()
    if "iteminfo" in low and "myvscloud" in low:
        return load_fixture("webtrac", WEBTRAC_ITEMINFO_SLUG)
    if "specialty" in low.replace(" ", "") or "category=specialty" in low.replace(" ", ""):
        return load_fixture("webtrac", WEBTRAC_SPECIALTY_CATALOG_SLUG)
    if "search.html" in low and ("type=camp" in low.replace(" ", "") or "module=ar" in low):
        return load_fixture("webtrac", WEBTRAC_CATALOG_SLUG)
    if "myvscloud" in low or "webtrac" in low:
        return load_fixture("webtrac", WEBTRAC_CATALOG_SLUG)
    if "program_details" in low:
        return load_fixture("myrec", MYREC_PROGRAM_SLUG)
    if "myrec.com" in low:
        return load_platform_fixture("myrec")
    if "communityed.org" in low:
        return load_platform_fixture("community_ed")
    slug = _host_slug(url)
    for platform, seed_slug in SEED_FIXTURE.items():
        if slug == seed_slug or slug in seed_slug:
            return load_platform_fixture(platform)
    return url, "", []


async def fixture_fetch(url: str) -> tuple[str, list[dict]]:
    """Mock production fetch: return saved HTML for known fixture URLs only."""
    return _as_fetch(url)
