"""Part C Stage 4 — county-wide provider registry for regional sharing.

A Woburn gymnastics gym serves 6+ surrounding towns; without sharing, every
town re-searches and re-discovers it. Registry: data/shared/
provider_registry.json — host → {name, town, categories, parent_ready, urls}.

Flow:
  BEFORE searching a hole in town X → registry_coverage(X) may already cover the
  category within gap_share_radius_miles → coverage matrix gets covered_via,
  the search is skipped.
  AFTER a gap search finds providers → register_sessions() back-fills every
  in-radius town on the next matrix rebuild.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from config.settings import SETTINGS
from config.town_geo import distance_between
from src.categorizer import categorize_sessions

logger = logging.getLogger(__name__)

REGISTRY_PATH = Path("data/shared/provider_registry.json")

# Long-tail categories so rare that a parent will drive farther for them.
RARE_CATEGORIES = frozenset(
    {"fencing", "sailing", "equestrian", "horseback_riding", "rowing", "crew",
     "curling", "speed_skating", "figure_skating", "circus_arts", "surfing"}
)


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_registry(reg: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=1, sort_keys=True))


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().replace("www.", "")


def register_sessions(town: str, sessions: list[dict], *, use_llm: bool = True) -> int:
    """Fold a town's (verified) sessions into the registry. Returns hosts touched."""
    reg = load_registry()
    sessions = categorize_sessions(sessions, use_llm=use_llm)
    touched = set()
    for s in sessions:
        url = s.get("register_url") or s.get("info_url") or ""
        host = _host(url)
        if not host:
            continue
        entry = reg.setdefault(
            host, {"name": "", "town": town, "categories": [], "parent_ready": False,
                   "urls": []},
        )
        entry.setdefault("town", town)
        if s.get("name") and len(s["name"]) > len(entry.get("name", "")):
            entry["name"] = s["name"]
        cats = set(entry.get("categories") or []) | set(s.get("categories") or [])
        entry["categories"] = sorted(cats)
        if s.get("parent_verdict") == "parent_ready" or s.get("verdict") in (
            "parent_ready", "info_confirmed"
        ):
            entry["parent_ready"] = True
        urls = entry.get("urls") or []
        if url and url not in urls:
            entry["urls"] = (urls + [url])[:10]
        touched.add(host)
    save_registry(reg)
    logger.info("provider registry: %d host(s) registered/updated for %s", len(touched), town)
    return len(touched)


def registry_coverage(town: str, *, registry: dict | None = None) -> dict[str, str]:
    """category → providing town, for every category covered by a registered
    parent-ready provider within the sharing radius of `town`."""
    reg = registry if registry is not None else load_registry()
    base_radius = float(SETTINGS.get("gap_share_radius_miles", 10))
    rare_radius = float(SETTINGS.get("gap_share_radius_rare_miles", 15))
    out: dict[str, str] = {}
    for host, entry in reg.items():
        if not entry.get("parent_ready"):
            continue
        provider_town = entry.get("town") or ""
        if not provider_town:
            continue
        dist = 0.0 if provider_town == town else (distance_between(town, provider_town) or 9e9)
        for cat in entry.get("categories") or []:
            radius = rare_radius if cat in RARE_CATEGORIES else base_radius
            if dist <= radius and cat not in out:
                out[cat] = provider_town
    return out


def skippable_holes(town: str, holes: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Split holes into (still-searchable, {category: covered_via_town})."""
    coverage = registry_coverage(town)
    keep: list[dict] = []
    skipped: dict[str, str] = {}
    for h in holes:
        cat = h.get("category")
        if cat and cat in coverage and coverage[cat] != town:
            skipped[cat] = coverage[cat]
        else:
            keep.append(h)
    return keep, skipped
