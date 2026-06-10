"""Capture real provider HTML via the production crawl path for characterization tests."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.crawl import fetch_page_text_and_links  # noqa: E402

FIXTURE_TARGETS: dict[str, str] = {
    "webtrac": "https://www.jwhayden.org/summer-camp",
    "myrec": "https://lexrecma.myrec.com/info/activities/activities.aspx",
    "community_ed": "https://lexingtoncommunityed.org/lexplorations/",
    "generic": "https://summersedgedaycamp.com/",
}

WEBTRAC_CATALOG_URL = (
    "https://majwhaydenweb.myvscloud.com/webtrac/web/search.html?module=AR&type=CAMP"
)
WEBTRAC_SPECIALTY_CATALOG_URL = (
    "https://majwhaydenweb.myvscloud.com/webtrac/web/search.html"
    "?module=AR&category=Specialty+Camps&display=detail"
)


def _fixture_slug(url: str, *, label: str = "") -> str:
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    host = host.replace(":", "_")
    if label:
        return f"{host}.{label}"
    low = url.lower()
    if "iteminfo" in low:
        return f"{host}.iteminfo"
    if "program_details" in low:
        return f"{host}.program_detail"
    if "search.html" in low and "specialty" in low.replace(" ", ""):
        return f"{host}.catalog_specialty"
    if "search.html" in low and "type=camp" in low.replace(" ", ""):
        return f"{host}.catalog"
    return host


async def _capture_one(platform: str, url: str, root: Path, *, label: str = "") -> Path:
    html, links = await fetch_page_text_and_links(url, caller=f"capture_fixtures:{platform}")
    plat_dir = root / platform
    plat_dir.mkdir(parents=True, exist_ok=True)
    slug = _fixture_slug(url, label=label)
    html_path = plat_dir / f"{slug}.html"
    meta_path = plat_dir / f"{slug}.meta.json"
    html_path.write_text(html or "", encoding="utf-8")
    meta = {
        "url": url,
        "platform": platform,
        "fixture_slug": slug,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "html_bytes": len(html or ""),
        "link_count": len(links),
        "links": links[:800],
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  {platform}: {slug} — {len(html or '')} bytes, {len(links)} links")
    return html_path


def _first_link(links: list[dict], pattern: str) -> str | None:
    for link in links:
        u = link.get("url", "")
        if pattern in u.lower():
            return u
    return None


async def capture_all(root: Path) -> None:
    for platform, url in FIXTURE_TARGETS.items():
        await _capture_one(platform, url, root)
    await _capture_one("webtrac", WEBTRAC_CATALOG_URL, root, label="catalog")
    await _capture_one("webtrac", WEBTRAC_SPECIALTY_CATALOG_URL, root, label="catalog_specialty")

    catalog_meta = root / "webtrac" / "majwhaydenweb.myvscloud.com.catalog.meta.json"
    if catalog_meta.exists():
        webtrac_meta = json.loads(catalog_meta.read_text(encoding="utf-8"))
        iteminfo = _first_link(webtrac_meta.get("links", []), "iteminfo")
        if iteminfo:
            await _capture_one("webtrac", iteminfo, root, label="iteminfo")

    listing_meta = root / "myrec" / "lexrecma.myrec.com.meta.json"
    if listing_meta.exists():
        myrec_meta = json.loads(listing_meta.read_text(encoding="utf-8"))
        program = _first_link(myrec_meta.get("links", []), "program_details.aspx")
        if program:
            program = re.sub(r"#.*$", "", program)
            await _capture_one("myrec", program, root, label="program_detail")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("tests/fixtures"))
    args = ap.parse_args()
    print("Capturing fixtures via fetch_page_text_and_links...")
    asyncio.run(capture_all(args.root))
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
