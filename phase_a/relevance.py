"""Decide whether an enumerated session is in the current program focus.

Right now the project targets YOUTH SUMMER programs only:
  - child/day camps, summer sports clinics, kid workshops/classes
Explicitly NOT:
  - adult or senior classes, memberships, leagues, fundraisers/lunches/trips,
    and non-summer (fall/winter/spring/year-round) offerings.

This is a fast, deterministic heuristic so it can run over hundreds of sessions
without LLM cost. It is intentionally conservative on the "drop" side for the
obvious adult/non-program noise, and lenient toward anything that looks like a
camp/clinic/workshop or carries a summer signal. The focus is configurable
(SETTINGS["program_focus"]) so we can widen scope later.
"""

from __future__ import annotations

import re

# Hard drops: clearly adult/senior or not a registrable kids program at all.
# These never go to the LLM tie-breaker.
HARD_DROP_REASONS = frozenset({"adult", "non-program", "adult-fitness", "off-season", "empty"})

# Ambiguous drops: heuristic couldn't find youth/summer/camp signal — LLM may recover.
AMBIGUOUS_DROP_REASONS = frozenset({"no-signal"})

_ADULT_RE = re.compile(
    r"\b(adult|adults|grown[\s-]?up|senior|seniors|18\s*\+|21\s*\+|"
    r"men'?s|women'?s|over\s*1[8-9]|over\s*2\d)\b",
    re.IGNORECASE,
)
_NONPROGRAM_RE = re.compile(
    r"\b(membership|memberships|scholarship|donation|donate|fundraiser|fund\b|"
    r"gala|lunch|lunches|gift\s*card|punch\s*pass|drop[\s-]?in|locker|"
    r"sponsor|volunteer|trip|trips|league|boot\s*camp|bootcamp|"
    r"open\s*(gym|play|skate|swim)|public\s*skate|stick\s*&\s*puck)\b",
    re.IGNORECASE,
)
_ADULT_FITNESS_RE = re.compile(
    r"\b(yoga|pilates|zumba|spin\b|cycling|aerobics|cardio|"
    r"strength|crossfit|bootcamp|pickleball)\b",
    re.IGNORECASE,
)

# Positive signals.
_CAMP_TYPE_RE = re.compile(
    r"\b(camp|camps|clinic|clinics|workshop|workshops|academy|"
    r"day\s*camp|sports?\s*camp)\b",
    re.IGNORECASE,
)
_YOUTH_RE = re.compile(
    r"\b(kid|kids|child|children|youth|junior|jr\.?|teen|teens|tween|"
    r"camper|campers|cit\b|leader\s*in\s*training|lit\b|"
    r"pre[\s-]?k|preschool|kindergarten|grade|grades|boys?|girls?|"
    r"toddler|elementary|middle\s*school)\b",
    re.IGNORECASE,
)

# Season detection.
_SUMMER_RE = re.compile(
    r"\b(summer|jun(e|\.)?|jul(y|\.)?|aug(ust|\.)?)\b|\b0?[678]/\d{1,2}",
    re.IGNORECASE,
)
_OTHER_SEASON_RE = re.compile(
    r"\b(fall|autumn|winter|spring|"
    r"sept(ember)?|oct(ober)?|nov(ember)?|dec(ember)?|"
    r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?)\b|\b(0?9|1[012])/\d{1,2}",
    re.IGNORECASE,
)


def _age_is_adult(blob: str) -> bool:
    """True only when an explicit minimum age says adult (>=18)."""
    if re.search(r"\b1[8-9]\s*(?:\+|and\s*up|&\s*up)\b|\b2\d\s*\+", blob, re.IGNORECASE):
        return True
    return False


def is_hard_drop(reason: str) -> bool:
    return reason in HARD_DROP_REASONS


def is_ambiguous(reason: str) -> bool:
    """True when the heuristic drop/keep is uncertain enough for LLM review."""
    return reason in AMBIGUOUS_DROP_REASONS


def classify_session(
    name: str,
    *,
    ages: str = "",
    dates: str = "",
    price: str = "",
    text: str = "",
    register_url: str = "",
    platform: str = "",
    focus: str = "youth_summer",
) -> tuple[bool, str]:
    """Return (keep, reason). reason is a short tag for auditing."""
    blob = " ".join(x for x in (name, ages, dates, text) if x).strip()
    # roadmap2 Phase 3: a row can still carry hard evidence (age/date/price) even
    # when its name is empty (needs_name) or keyword-free.
    has_evidence = bool((ages or "").strip() or (dates or "").strip() or (price or "").strip())
    if not blob and not has_evidence:
        return False, "empty"

    if focus != "youth_summer":
        return True, "no-filter"

    # 1) hard drops
    if _ADULT_RE.search(blob) or _age_is_adult(blob):
        return False, "adult"
    if _NONPROGRAM_RE.search(blob):
        return False, "non-program"
    if _ADULT_FITNESS_RE.search(blob) and not _YOUTH_RE.search(blob):
        return False, "adult-fitness"

    summer = bool(_SUMMER_RE.search(blob))
    other_season = bool(_OTHER_SEASON_RE.search(blob))

    if other_season and not summer:
        return False, "off-season"

    camp_type = bool(_CAMP_TYPE_RE.search(blob))
    youth = bool(_YOUTH_RE.search(blob))

    if platform == "webtrac":
        return True, "camp-catalog"

    if platform == "catalog_grid":
        if camp_type or summer:
            return True, "youth-summer"
        return False, "no-signal"

    if camp_type or youth or summer:
        return True, "youth-summer"

    # roadmap2 Phase 3: judge the thing, not just the label. A row sitting on a
    # real registration platform AND carrying age/date/price evidence is a
    # registrable program regardless of whether its name contains "camp".
    from phase_b.registration import is_registration_platform_url

    if has_evidence and is_registration_platform_url(register_url):
        return True, "registrable-evidence"

    return False, "no-signal"


def filter_sessions(sessions: list[dict], focus: str = "youth_summer") -> tuple[list[dict], list[dict]]:
    """Split sessions into (kept, dropped). Annotates each with `_focus_reason`."""
    kept, dropped = [], []
    for s in sessions:
        keep, reason = classify_session(
            s.get("name", ""),
            ages=s.get("ages", ""),
            dates=s.get("dates", ""),
            price=s.get("price", ""),
            text=s.get("text", ""),
            register_url=s.get("register_url", ""),
            platform=s.get("platform", ""),
            focus=focus,
        )
        s = {**s, "_focus_reason": reason}
        (kept if keep else dropped).append(s)
    return kept, dropped
