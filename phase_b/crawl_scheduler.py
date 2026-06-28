"""Sort and tier harvest seeds for efficient Phase B crawling."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from config.settings import SETTINGS
from phase_a.camp_hosts import is_camp_host_seed_url
from shared.geo_filter import is_out_of_state_url

_IMAGE_URL_RE = re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|ico)(\?|$)", re.I)


def is_media_url(url: str) -> bool:
    return bool(_IMAGE_URL_RE.search((url or "").lower()))


def seed_tier(candidate: dict) -> str:
    if candidate.get("preferred") == "true":
        return "preferred"
    if is_camp_host_seed_url(candidate.get("url", "")) or candidate.get("classified_as") == "camp":
        return "camp_host"
    if candidate.get("classified_as") == "directory":
        return "directory"
    return "unknown"


def crawl_profile(tier: str) -> dict:
    profiles = SETTINGS.get("crawl_tier_profiles") or {}
    return profiles.get(tier, profiles.get("unknown", {}))


def sort_seeds(candidates: list[tuple[int, dict]]) -> list[tuple[int, dict]]:
    order = {"preferred": 0, "camp_host": 1, "directory": 2, "unknown": 3, "guide": 4}

    def key(item: tuple[int, dict]) -> tuple:
        c = item[1]
        tier = seed_tier(c)
        if c.get("classified_as") == "guide":
            tier = "guide"
        return (order.get(tier, 9), c.get("url", ""))

    return sorted(candidates, key=key)


def should_skip_seed(candidate: dict, *, state: str = "MA") -> tuple[bool, str]:
    url = candidate.get("url", "")
    oos, reason = is_out_of_state_url(url, title=candidate.get("title", ""), state=state)
    if oos:
        return True, reason
    return False, ""
