"""One-off: capture live hub search pages to data/_fixtures/ for golden tests.

Uses the project's Playwright fetch (crawl.fetch_rendered) so it follows the
same render path the adapters use. Network-only; never run in tests.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.hubs import hub_search_url  # noqa: E402
from phase_b.crawl import fetch_rendered  # noqa: E402

FIX = ROOT / "data" / "_fixtures"


async def grab(url: str, out: Path, *, wait: str = "networkidle", timeout: int = 35) -> int:
    html = await fetch_rendered(url, wait=wait, timeout_s=timeout)
    n = len(html or "")
    if html:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"  saved {n:>8} bytes -> {out.relative_to(ROOT)}")
    else:
        print(f"  FAILED (no html) {url}")
    return n


async def main() -> int:
    targets = [
        ("camp_invention",
         hub_search_url("camp_invention", zip="02421", radius=25),
         FIX / "camp_invention" / "02421_25mi.html", "networkidle"),
        ("skyhawks",
         hub_search_url("skyhawks", zip="02421", radius=10),
         FIX / "configio" / "skyhawks_02421_10mi.html", "networkidle"),
        ("idtech_loc",
         hub_search_url("idtech", city="Lexington", state="MA", page=1),
         FIX / "idtech" / "location-search_lexington.html", "networkidle"),
    ]
    for name, url, out, wait in targets:
        print(f"[{name}] {url}")
        try:
            await grab(url, out, wait=wait)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
