"""Fingerprint the registration/web platform for every discovered host.

Input:  unique hosts from data/candidates.csv + data/camp_links.csv
Output: data/platform_fingerprint_report.csv
        (host, seed_url, final_url, status, page_signals, links_to, error)

Usage:
    ./venv/bin/python -m scripts.fingerprint_all_candidates [--town Lexington] [--limit N]
"""

import argparse
import asyncio
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.platforms_registry import PLATFORM_SIGNATURES  # noqa: E402

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

from src.csv_mirror import write_csv_bundle
from src.data_layout import camp_links_csv, candidates_csv, platform_fingerprint_csv

REPORT_PATH = platform_fingerprint_csv()
LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

# Hosts that are never providers (guides, social, search) — skip probing.
_SKIP_HOST_RE = re.compile(
    r"facebook|instagram|twitter|youtube|linkedin|google|macaronikid|"
    r"mommypoppins|bostoncentral|activityhero|kidsoutandabout|teenlife|"
    r"acacamps|wikipedia|yelp",
    re.IGNORECASE,
)


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def collect_hosts(town: str | None) -> dict[str, str]:
    """host -> best seed URL, from candidates.csv + camp_links.csv."""
    by_host: dict[str, str] = {}

    cand = candidates_csv()
    if cand.exists():
        with open(cand, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if town and row.get("town") and row.get("town") != town:
                    continue
                url = row.get("url", "")
                h = _host(url)
                if h and not _SKIP_HOST_RE.search(h):
                    by_host.setdefault(h, url)

    links = camp_links_csv()
    if links.exists():
        with open(links, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if town and row.get("town_hint") and row.get("town_hint") != town:
                    continue
                url = row.get("url", "")
                h = _host(url)
                if h and not _SKIP_HOST_RE.search(h):
                    # Prefer a shallow seed: host root beats deep harvest links.
                    by_host.setdefault(h, f"https://{h}/")

    return by_host


async def probe(client: httpx.AsyncClient, host: str, url: str, sem: asyncio.Semaphore) -> dict:
    info = {
        "host": host,
        "seed_url": url,
        "final_url": "",
        "status": "",
        "page_signals": "",
        "links_to": "",
        "error": "",
    }
    async with sem:
        try:
            r = await client.get(url, follow_redirects=True, timeout=20)
        except Exception as exc:  # noqa: BLE001
            info["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
            return info

    info["status"] = str(r.status_code)
    info["final_url"] = str(r.url)
    html = (r.text or "").lower()

    page_hits: set[str] = set()
    link_hits: set[str] = set()
    for pid, spec in PLATFORM_SIGNATURES.items():
        if any(re.search(p, html) for p in spec["html_patterns"]):
            page_hits.add(pid)
    for href in LINK_RE.findall(html):
        for pid, spec in PLATFORM_SIGNATURES.items():
            if any(re.search(p, href) for p in spec["html_patterns"]):
                link_hits.add(pid)

    info["page_signals"] = ";".join(sorted(page_hits))
    info["links_to"] = ";".join(sorted(link_hits))
    return info


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fingerprint all candidate hosts")
    parser.add_argument("--town", default=None, help="Limit to one town's candidates")
    parser.add_argument("--limit", type=int, default=None, help="Max hosts to probe")
    args = parser.parse_args()

    hosts = collect_hosts(args.town)
    items = sorted(hosts.items())
    if args.limit:
        items = items[: args.limit]
    print(f"Probing {len(items)} host(s)...")

    sem = asyncio.Semaphore(8)
    async with httpx.AsyncClient(headers={"User-Agent": UA}) as client:
        results = await asyncio.gather(
            *[probe(client, h, u, sem) for h, u in items]
        )

    cols = ["host", "seed_url", "final_url", "status", "page_signals", "links_to", "error"]
    write_csv_bundle(
        REPORT_PATH,
        results,
        cols,
        title="Platform fingerprint report",
        description="Registration platform signals per discovered host.",
    )

    detected = sum(1 for r in results if r["page_signals"] or r["links_to"])
    errors = sum(1 for r in results if r["error"])
    print(f"Wrote {REPORT_PATH} — {len(results)} hosts, {detected} with platform signals, {errors} errors")


if __name__ == "__main__":
    asyncio.run(main())
