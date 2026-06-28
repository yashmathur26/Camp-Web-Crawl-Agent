"""Part C — Gemma demand ranking for gap categories (operator request).

"Most needed" = what a Massachusetts parent is most likely to search for.
Gemma3:4b scores every category 1-10 once; scores are cached county-wide
(cache/category_demand.json) because demand is town-independent — one model
pass serves all 54 towns. Holes are then searched highest-demand-first, and
the coverage matrix records demand per category.

Fail-open: model down -> deterministic prior (core=8, mainstream sports/arts
=6, niche=3) so ordering never blocks a run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config.gap_taxonomy import ALL_CATEGORIES, CORE_CATEGORIES
from config.settings import SETTINGS
from shared.llm import OllamaError, chat, is_available

logger = logging.getLogger(__name__)

import os as _os
_CACHE_PATH = Path(_os.environ.get("FIREFLY_CACHE_ROOT", "cache")) / "category_demand.json"

_RANKER_SYSTEM = """You are ranking youth summer camp categories by PARENT DEMAND
in suburban Massachusetts: how many parents would search for each when planning
summer? Consider participation rates (swim/soccer/basketball/day camp are huge;
curling/quidditch tiny), age-band breadth, and whether parents seek it as a
dedicated camp. Return JSON only:
{"demand": {"<slug>": <1-10 integer>, ...}}  — every slug you were given."""

# Deterministic prior (fail-open + blend sanity).
_MAINSTREAM = {
    "swim", "soccer", "basketball", "baseball", "art", "dance", "gymnastics",
    "theater", "music", "stem", "coding", "robotics", "nature", "cooking",
    "tennis", "lacrosse", "martial_arts", "preschool", "general_day_camp",
    "sports_multi",
}


def _prior(cat: str) -> int:
    if cat in CORE_CATEGORIES:
        return 8
    if cat in _MAINSTREAM:
        return 6
    return 3


def _load() -> dict[str, int]:
    if _CACHE_PATH.exists():
        try:
            return {k: int(v) for k, v in json.loads(_CACHE_PATH.read_text()).items()}
        except (json.JSONDecodeError, OSError, ValueError):
            return {}
    return {}


def demand_scores(*, use_llm: bool = True) -> dict[str, int]:
    """slug -> demand 1-10 for every category; Gemma-scored once then cached."""
    scores = _load()
    missing = [c for c in ALL_CATEGORIES if c not in scores]
    if missing and use_llm and is_available():
        for i in range(0, len(missing), 25):
            batch = missing[i : i + 25]
            try:
                resp = chat(
                    _RANKER_SYSTEM,
                    json.dumps({"slugs": batch}),
                    model=SETTINGS.get("ollama_filter_model") or SETTINGS.get("ollama_model"),
                    temperature=0.0,
                    timeout=90,
                    num_predict=1024,
                    purpose="category_demand_ranker",
                )
            except OllamaError as exc:
                logger.warning("demand ranker batch failed: %s", exc)
                break
            for slug, val in (resp.get("demand") or {}).items():
                if slug in ALL_CATEGORIES:
                    try:
                        scores[slug] = max(1, min(10, int(val)))
                    except (TypeError, ValueError):
                        continue
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(scores, indent=1, sort_keys=True))
    return {c: scores.get(c, _prior(c)) for c in ALL_CATEGORIES}


def rank_holes(holes: list[dict], *, use_llm: bool = True) -> list[dict]:
    """Order holes: core tier first, then demand desc, then static priority.
    Annotates each hole with `demand`."""
    scores = demand_scores(use_llm=use_llm)
    for h in holes:
        cat = h.get("category") or h.get("hole_id", "").replace("missing_category_", "")
        h["demand"] = scores.get(cat, _prior(cat) if cat else 2)
    return sorted(
        holes,
        key=lambda h: (
            0 if (h.get("category") in CORE_CATEGORIES) else 1,
            -int(h.get("demand", 0)),
            h.get("priority", 5),
        ),
    )
