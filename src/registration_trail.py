"""Phase B.6: registration trail for needs_trail sessions and 0-session providers."""

from __future__ import annotations

import asyncio
import csv
import logging
from pathlib import Path
from urllib.parse import urlparse

from config.settings import SETTINGS
from src.data_layout import (
    parent_verdict_csv,
    quality_tier_csv,
    refresh_town_index,
    trail_log_txt,
)
from src.camp_validator import make_link_follow_gate
from src.crawl import walk_site
from src.platforms import enumerate_provider
from src.registration import is_registration_platform_url, registration_url_priority
from src.session_quality import classify_session_tier, split_sessions
from src.sessions import SESSION_CSV_COLUMNS, host_of

logger = logging.getLogger(__name__)


async def _trail_one(url: str, *, town_hint: str = "") -> dict:
    max_pages = int(SETTINGS.get("trail_max_pages", 12))
    max_depth = int(SETTINGS.get("trail_max_depth", 4))
    walk = await walk_site(
        url,
        max_depth,
        max_pages,
        focused=True,
        delay_seconds=SETTINGS.get("focused_delay_seconds", 1.5),
        stop_on_catalog=SETTINGS.get("focused_stop_on_catalog", True),
        link_gate=make_link_follow_gate() if SETTINGS.get("ollama_link_follow") else None,
    )
    best_url = url
    best_score = 0
    for link in walk.links:
        u = link.get("url", "")
        score = registration_url_priority(u)
        if score > best_score:
            best_score = score
            best_url = u
    if best_score > 0 and is_registration_platform_url(best_url):
        result = await enumerate_provider(best_url, town_hint=town_hint)
        return {
            "seed": url,
            "catalog_url": best_url,
            "platform": result.get("platform", ""),
            "sessions": result.get("sessions", []),
            "pages": len(walk.page_text_by_url),
        }
    return {
        "seed": url,
        "catalog_url": best_url if best_score > 0 else "",
        "platform": "trail",
        "sessions": [],
        "pages": len(walk.page_text_by_url),
    }


def _trail_priority_seeds(town: str) -> list[str]:
    """Phase P failures first, then needs_trail CSV."""
    slug = town.lower().replace(" ", "_")
    priority: list[str] = []
    for verdict_file in (
        parent_verdict_csv(town, "fetch_failed"),
        parent_verdict_csv(town, "brochure_only"),
        quality_tier_csv(town, "needs_trail"),
    ):
        path = Path(verdict_file)
        if not path.exists():
            continue
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                u = row.get("register_url") or row.get("source_url", "")
                if u:
                    priority.append(u)
    return list(dict.fromkeys(priority))


async def run_registration_trail(
    town: str,
    *,
    needs_trail_csv: Path | str | None = None,
    zero_session_seeds: list[str] | None = None,
    concurrency: int = 2,
) -> list[dict]:
    slug = town.lower().replace(" ", "_")
    seeds: list[str] = _trail_priority_seeds(town)
    seeds.extend(zero_session_seeds or [])
    if needs_trail_csv is None:
        needs_trail_csv = quality_tier_csv(town, "needs_trail")
    path = Path(needs_trail_csv)
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                u = row.get("register_url") or row.get("source_url", "")
                if u:
                    seeds.append(u)
    seeds = list(dict.fromkeys(seeds))
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []

    async def one(u: str) -> dict:
        async with sem:
            try:
                return await _trail_one(u, town_hint=town)
            except Exception as exc:  # noqa: BLE001
                logger.warning("trail failed for %s: %s", u, exc)
                return {"seed": u, "catalog_url": "", "platform": "ERROR", "sessions": [], "pages": 0}

    results = list(await asyncio.gather(*[one(u) for u in seeds]))
    log_path = trail_log_txt(town)
    lines = [f"{town} registration trail — {len(seeds)} seeds", "=" * 60, ""]
    for r in results:
        lines.append(f"Seed: {r['seed']}")
        lines.append(f"  Catalog: {r.get('catalog_url') or '(none)'}")
        lines.append(f"  Platform: {r.get('platform')}  Sessions: {len(r.get('sessions', []))}")
        lines.append("")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    refresh_town_index(town)
    return results


def merge_trail_sessions(trail_results: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for r in trail_results:
        for s in r.get("sessions", []):
            key = s.get("register_url", "")
            if key and key not in seen:
                seen.add(key)
                tier, _ = classify_session_tier(s)
                if tier == "registrable":
                    out.append(s)
    return out
