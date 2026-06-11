"""roadmap2 Phase 6 — process-level fetch cache keyed on normalize_url.

lexingtonma.gov re-derives the same MyRec catalog that the dedicated MyRec
provider already crawls, so the run fetches identical URLs twice. A simple
in-process cache (one run = one process) keyed on the normalized URL + fetch
kind avoids the double-fetch. Gated by SETTINGS["b5_fetch_cache"].
"""

from __future__ import annotations

import logging

from config.settings import SETTINGS
from src.urls import normalize_url

logger = logging.getLogger(__name__)

_CACHE: dict[tuple[str, str], tuple[str, list[dict]]] = {}
_stats = {"hits": 0, "misses": 0}


def enabled() -> bool:
    return bool(SETTINGS.get("b5_fetch_cache", True))


def _key(url: str, kind: str) -> tuple[str, str]:
    return (normalize_url(url) or url, kind or "")


def get(url: str, *, kind: str = "") -> tuple[str, list[dict]] | None:
    if not enabled():
        return None
    hit = _CACHE.get(_key(url, kind))
    if hit is not None:
        _stats["hits"] += 1
        # Return copies so callers mutating links don't corrupt the cache.
        return hit[0], [dict(link) for link in hit[1]]
    _stats["misses"] += 1
    return None


def put(url: str, text: str, links: list[dict], *, kind: str = "") -> None:
    if not enabled():
        return
    # Don't cache empty/failed fetches — a later retry may succeed.
    if not (text or "").strip():
        return
    _CACHE[_key(url, kind)] = (text, [dict(link) for link in links])


def reset() -> None:
    """Clear the cache (per-run / test isolation)."""
    _CACHE.clear()
    _stats["hits"] = 0
    _stats["misses"] = 0


def stats() -> dict[str, int]:
    return dict(_stats)
