"""Parent camp category taxonomy for gap-fill Part C.

Generated programmatically from the activity lists in config/keywords.py
(Part C Stage 1) — one source of truth, ~150 categories instead of 24.

Tiers:
  CORE_CATEGORIES  — must exist in EVERY town's catalog; searched unconditionally.
  LONG_TAIL        — searched when missing; may resolve to nearest-town coverage.

Backward compatibility: GAP_CATEGORIES / GAP_SEARCH_TEMPLATES keep their old
shape (existing callers in parent_auditor/gap_finder keep working).
"""

from __future__ import annotations

import re

from config.keywords import (
    _ARTS_ACTIVITIES,
    _FUN_ACTIVITIES,
    _SPORTS_ACTIVITIES,
    _STEM_ACTIVITIES,
)


def slugify(activity: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", activity.lower()).strip("_")


# --------------------------------------------------------------------------- #
# Tier 1 — CORE: a parent in any town expects at least one of each.
# --------------------------------------------------------------------------- #
CORE_CATEGORIES: tuple[str, ...] = (
    "general_day_camp", "sports_multi", "soccer", "basketball", "swim",
    "art", "music", "theater", "dance", "stem", "coding", "robotics",
    "nature", "cooking", "preschool", "special_needs", "teen_leadership",
)

# Tier 2 — LONG TAIL: every activity in keywords.py, slug → display name.
LONG_TAIL: dict[str, str] = {
    slugify(a): a
    for a in (
        _SPORTS_ACTIVITIES + _ARTS_ACTIVITIES + _STEM_ACTIVITIES + _FUN_ACTIVITIES
    )
}

# Core categories that aren't literal activity slugs get display names here.
_CORE_DISPLAY: dict[str, str] = {
    "general_day_camp": "day camp",
    "sports_multi": "multi sport",
    "stem": "STEM",
    "teen_leadership": "teen leadership",
    "special_needs": "special needs adaptive",
    "preschool": "preschool",
    "art": "art",
    "music": "music",
    "theater": "theater",
    "dance": "dance",
    "nature": "nature",
    "cooking": "cooking",
    "soccer": "soccer",
    "basketball": "basketball",
    "swim": "swim",
    "coding": "coding",
    "robotics": "robotics",
}

ALL_CATEGORIES: dict[str, str] = {**LONG_TAIL, **_CORE_DISPLAY}

# --------------------------------------------------------------------------- #
# Query variants (Stage 3.2 multi-variant searches use these in order).
# --------------------------------------------------------------------------- #
QUERY_TEMPLATES: tuple[str, ...] = (
    "{town} MA youth {activity} summer camp",
    "{activity} summer camp kids near {town} Massachusetts",
    "{activity} summer clinic registration {town} MA 2026",
)


def queries_for_category(category: str, town: str) -> list[str]:
    """Up to 3 query variants for a category, in escalation order."""
    activity = ALL_CATEGORIES.get(category) or category.replace("_", " ")
    return [t.format(town=town, activity=activity) for t in QUERY_TEMPLATES]


# --------------------------------------------------------------------------- #
# Parent synonyms: how parents search → category slug. Feeds the categorizer
# (Stage 2) and the website's search→category mapping later.
# --------------------------------------------------------------------------- #
PARENT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "voice_and_singing": ("singing", "vocal", "choir", "chorus", "a cappella"),
    "ninja_warrior": ("obstacle", "parkour", "american ninja"),
    "soccer": ("futsal", "football club", "fc academy", "striker"),
    "basketball": ("hoops", "ballers", "3v3", "3 on 3"),
    "swim": ("swimming", "aquatics", "swim team", "learn to swim"),
    "stem": ("steam", "science technology", "maker", "tinker"),
    "coding": ("programming", "code", "scratch", "python", "minecraft modding"),
    "robotics": ("lego robotics", "vex", "first lego", "battlebots", "robot"),
    "art": ("arts and crafts", "drawing", "painting", "studio art", "crafts"),
    "pottery": ("ceramics", "clay", "wheel throwing"),
    "theater": ("drama", "acting", "musical theater", "stagecraft", "improv"),
    "dance": ("ballet", "hip hop", "jazz dance", "tap", "choreography"),
    "music": ("band", "orchestra", "instrument", "jam", "rock band"),
    "piano": ("keyboard",),
    "drumming": ("percussion", "drums"),
    "guitar": ("ukulele", "strings"),
    "gymnastics": ("tumbling", "acro", "acrobatics", "aerial"),
    "martial_arts": ("karate", "taekwondo", "kung fu", "self defense", "mma"),
    "nature": ("outdoor", "wildlife", "audubon", "farm", "forest", "environmental"),
    "cooking": ("culinary", "baking", "chef", "test kitchen", "food"),
    "horseback_riding": ("equestrian", "pony", "stable", "riding"),
    "rock_climbing": ("bouldering", "climbing wall"),
    "sailing": ("boating", "yacht club", "kayak", "paddle"),
    "preschool": ("pre-k", "pre k", "toddler", "early childhood", "little"),
    "teen_leadership": ("cit", "lit", "counselor in training", "leader in training"),
    "special_needs": ("adaptive", "inclusion", "aspire", "autism", "sensory"),
    "general_day_camp": ("day camp", "summer camp", "full day", "traditional camp",
                         "lower camp", "upper camp", "junior camp", "teen camp",
                         "kindercamp", "camp lpc"),
    "sports_multi": ("multi-sport", "multi sport", "all sports", "sports sampler"),
    "chess": ("chess club", "grandmaster", "bughouse"),
    "video_game_design": ("esports", "gaming", "game dev"),
    "filmmaking": ("film", "video production", "youtube", "movie making"),
    "creative_writing": ("writing", "authors", "storytelling", "poetry"),
    "fashion_design": ("sewing", "textile", "design studio"),
    "circus_arts": ("circus", "juggling", "trapeze", "aerial silks"),
    "track_and_field": ("track", "running club", "cross country"),
    "ice_hockey": ("hockey", "skating", "rink", "learn to skate"),
    "figure_skating": ("ice skating", "skate club"),
    "magic": ("magician", "wizards", "wands", "harry potter"),
    "dungeons_and_dragons": ("d&d", "dnd", "rpg", "tabletop"),
    "engineering": ("builders", "construction", "bridges", "catapult"),
    "fencing": ("epee", "foil", "sabre", "swordplay"),
}


def synonyms_for(category: str) -> tuple[str, ...]:
    return PARENT_SYNONYMS.get(category, ())


# --------------------------------------------------------------------------- #
# Backward compatibility (old 24-bucket API).
# --------------------------------------------------------------------------- #
GAP_CATEGORIES: tuple[str, ...] = CORE_CATEGORIES + tuple(
    s for s in LONG_TAIL if s not in CORE_CATEGORIES
)

GAP_SEARCH_TEMPLATES: dict[str, str] = {
    cat: QUERY_TEMPLATES[0].replace("{activity}", ALL_CATEGORIES.get(cat, cat.replace("_", " ")))
    for cat in GAP_CATEGORIES
}
