"""Population-scaled, adaptive per-town search budget (discovery-expansion
roadmap, Thread 1).

Replaces the old flat "53 keywords for every town / 40 gap searches for every
town" with a budget each town derives from three signals:

  1. POPULATION sets the ambition (ceiling): a smooth power curve, no cliffs.
       ceiling = BASE * (pop / 10_000) ** ALPHA  (+ institution boost, Phase A)
     ALPHA=0.38 is fitted to the operator's anchors — Boston (~676k) ≈ 5×, and
     Waltham (~65k) ≈ 2× a 10k town. (Framingham ~72k lands ~2.1×: it is
     genuinely Waltham-sized, so no pop curve can make it 3× while Waltham is 2×.)
  2. INSTITUTION COUNT (colleges + camp-hosting schools) raises the Phase A
     ceiling — each is its own provider surface to search.
  3. LIVE YIELD decides the realized count (YieldStopper): spend until new
     provider hosts dry up, capped by the ceiling. Productive towns ride to the
     ceiling; sleepy towns stop near the floor.

All constants are overridable via config.settings.SETTINGS.
"""

from __future__ import annotations

from config.college_registry import colleges_for
from config.keywords import (
    INSTITUTION_QUERY_TEMPLATES,
    PHASE_A_ACTIVITY_TERMS,
    PHASE_A_KEYWORDS,
    PHASE_C_KEYWORDS,
    TOWN_INSTITUTION_TEMPLATES,
)
from config.school_registry import school_counts, schools_for
from config.settings import SETTINGS
from config.town_geo import population_lookup

_DEFAULTS = {
    "budget_base_phase_a": 50,        # "aggressive" (operator pick)
    "budget_base_phase_c": 40,
    "budget_alpha": 0.38,
    "budget_pop_ref": 10_000,
    "budget_floor_phase_a": 25,
    "budget_floor_phase_c": 15,
    "budget_hardmax_phase_a": 400,    # under global max_searches_per_run=1000
    "budget_hardmax_phase_c": 200,
    "budget_yield_window": 10,
    "budget_default_population": 23_000,  # county median, for unknown towns
}
# Per-institution boost to the Phase A ceiling (search units).
_BOOST = {"college": 10, "private": 8, "public_high": 6, "public_district": 6, "trade": 6}


def _cfg(key: str):
    return SETTINGS.get(key, _DEFAULTS[key])


def population_of(town: str) -> int:
    pop = population_lookup(town)
    return pop if pop is not None else int(_cfg("budget_default_population"))


def institution_boost(town: str) -> int:
    """Extra Phase A searches a town earns for its camp-hosting institutions."""
    sc = school_counts(town)
    return (
        len(colleges_for(town)) * _BOOST["college"]
        + sc["private"] * _BOOST["private"]
        + sc["public_high"] * _BOOST["public_high"]
        + sc["public_district"] * _BOOST["public_district"]
        + sc["trade"] * _BOOST["trade"]
    )


def _ceiling(pop: int, base: float, floor: int, hardmax: int, boost: int = 0) -> int:
    raw = base * (pop / _cfg("budget_pop_ref")) ** _cfg("budget_alpha") + boost
    return int(max(floor, min(hardmax, round(raw))))


def town_budget(town: str) -> dict[str, int]:
    """Ceilings (max searches) for each phase. Realized counts are usually lower
    once the adaptive YieldStopper kicks in."""
    pop = population_of(town)
    return {
        "phase_a": _ceiling(
            pop, _cfg("budget_base_phase_a"), _cfg("budget_floor_phase_a"),
            _cfg("budget_hardmax_phase_a"), boost=institution_boost(town),
        ),
        "phase_c": _ceiling(
            pop, _cfg("budget_base_phase_c"), _cfg("budget_floor_phase_c"),
            _cfg("budget_hardmax_phase_c"),
        ),
        "population": pop,
        "institutions": institution_boost(town),
    }


def institution_queries(town: str) -> list[str]:
    """Curated college + school queries for a town (the must-run, high-yield slice
    the operator explicitly asked to surface). Empty for towns with no curated
    institutions — the generic TOWN_INSTITUTION_TEMPLATES in the tail still run."""
    out: list[str] = []
    for c in colleges_for(town):
        for tmpl in INSTITUTION_QUERY_TEMPLATES["college"]:
            out.append(tmpl.format(name=c["name"]))
    for s in schools_for(town):
        for tmpl in INSTITUTION_QUERY_TEMPLATES.get(s.get("type", ""), []):
            out.append(tmpl.format(name=s["name"]))
    return list(dict.fromkeys(out))


def prioritized_queries(town: str, state: str = "MA") -> tuple[list[str], list[str]]:
    """Return (must_run, tail).

    must_run = curated institution queries — always issued (not subject to the
               yield-stop), since they are the college/school camps we want.
    tail     = ordered long pool (core keywords → generic institution templates →
               activity expansions) — issued in order up to the ceiling, with the
               YieldStopper allowed to end early.
    """
    must = institution_queries(town)
    tail: list[str] = []
    tail += [f"{kw} {town}, {state}" for kw in PHASE_A_KEYWORDS]
    tail += [t.format(town=town, state=state) for t in TOWN_INSTITUTION_TEMPLATES]
    tail += [f"{act} youth summer camp {town}, {state}" for act in PHASE_A_ACTIVITY_TERMS]
    # Niche long-tail (the full activity composition). Only big towns' ceilings
    # reach this far; small towns stop well before it.
    tail += [f"{kw} {town}, {state}" for kw in PHASE_C_KEYWORDS]
    seen = {q.lower() for q in must}
    tail = [q for q in dict.fromkeys(tail) if q.lower() not in seen]
    return must, tail


class YieldStopper:
    """Adaptive early-stop on diminishing returns.

    Call record(hosts) after every search with the provider hosts it surfaced.
    should_stop() is True once at least `floor` searches have run AND the last
    `window` searches produced zero NEW unique hosts. The ceiling is enforced by
    the caller; this only ends a run *early* when it has gone dry.
    """

    def __init__(self, *, floor: int, window: int | None = None) -> None:
        self.floor = max(1, floor)
        self.window = window or int(_cfg("budget_yield_window"))
        self.count = 0
        self._recent_new: list[int] = []
        self._seen: set[str] = set()

    def record(self, hosts) -> None:
        new = 0
        for h in hosts or ():
            if h and h not in self._seen:
                self._seen.add(h)
                new += 1
        self.count += 1
        self._recent_new.append(new)
        if len(self._recent_new) > self.window:
            self._recent_new.pop(0)

    def should_stop(self) -> bool:
        if self.count < self.floor:
            return False
        if len(self._recent_new) < self.window:
            return False
        return sum(self._recent_new) == 0
