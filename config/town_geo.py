"""Part C Stage 4.1 — static geodata for the 54 Middlesex County municipalities.

(lat, lon) are town centers (sufficient for 10-15 mile radius sharing);
population is ~2020 census, used to order multi-town runs (big towns seed the
provider registry first).
"""

from __future__ import annotations

import math

TOWN_GEO: dict[str, tuple[float, float, int]] = {
    # town: (lat, lon, population)
    "Acton": (42.4851, -71.4328, 24021),
    "Arlington": (42.4154, -71.1565, 46308),
    "Ashby": (42.6779, -71.8203, 3193),
    "Ashland": (42.2612, -71.4634, 18832),
    "Ayer": (42.5612, -71.5898, 8479),
    "Bedford": (42.4906, -71.2760, 14383),
    "Belmont": (42.3956, -71.1776, 27295),
    "Billerica": (42.5584, -71.2689, 42119),
    "Boxborough": (42.4904, -71.5284, 5506),
    "Burlington": (42.5048, -71.1956, 26377),
    "Cambridge": (42.3736, -71.1097, 118403),
    "Carlisle": (42.5292, -71.3495, 5237),
    "Chelmsford": (42.5998, -71.3673, 36392),
    "Concord": (42.4604, -71.3489, 18491),
    "Dracut": (42.6703, -71.3023, 32617),
    "Dunstable": (42.6751, -71.4829, 3358),
    "Everett": (42.4084, -71.0537, 49075),
    "Framingham": (42.2793, -71.4162, 72362),
    "Groton": (42.6112, -71.5745, 11315),
    "Holliston": (42.2001, -71.4245, 14996),
    "Hopkinton": (42.2287, -71.5226, 18758),
    "Hudson": (42.3917, -71.5662, 20092),
    "Lexington": (42.4473, -71.2245, 34454),
    "Lincoln": (42.4259, -71.3039, 7014),
    "Littleton": (42.5384, -71.4884, 10141),
    "Lowell": (42.6334, -71.3162, 115554),
    "Malden": (42.4251, -71.0662, 66263),
    "Marlborough": (42.3459, -71.5523, 41793),
    "Maynard": (42.4334, -71.4495, 10746),
    "Medford": (42.4184, -71.1062, 59659),
    "Melrose": (42.4584, -71.0662, 29817),
    "Natick": (42.2834, -71.3495, 37006),
    "Newton": (42.3370, -71.2092, 88923),
    "North Reading": (42.5751, -71.0787, 15554),
    "Pepperell": (42.6659, -71.5884, 11604),
    "Reading": (42.5256, -71.0954, 25518),
    "Sherborn": (42.2390, -71.3701, 4401),
    "Shirley": (42.5445, -71.6495, 7431),
    "Somerville": (42.3876, -71.0995, 81045),
    "Stoneham": (42.4801, -71.0995, 23244),
    "Stow": (42.4370, -71.5056, 7174),
    "Sudbury": (42.3834, -71.4162, 18934),
    "Tewksbury": (42.6106, -71.2342, 31342),
    "Townsend": (42.6668, -71.7048, 9127),
    "Tyngsborough": (42.6767, -71.4245, 12380),
    "Wakefield": (42.5034, -71.0723, 27090),
    "Waltham": (42.3765, -71.2356, 65218),
    "Watertown": (42.3709, -71.1828, 35329),
    "Wayland": (42.3626, -71.3617, 13943),
    "Westford": (42.5793, -71.4378, 24643),
    "Weston": (42.3668, -71.3034, 11851),
    "Wilmington": (42.5465, -71.1737, 23349),
    "Winchester": (42.4523, -71.1370, 22970),
    "Woburn": (42.4793, -71.1523, 40876),
}

# Population-only lookup for major MA cities OUTSIDE the curated Middlesex set.
# Kept separate from TOWN_GEO on purpose: the discovery pipeline accepts any town
# and needs these for population-scaled search budgets, but they must NOT enter
# `towns_by_population()` / all-town runs (which iterate the 54 above). ~2020 census.
EXTRA_TOWN_POP: dict[str, int] = {
    "Boston": 675647,
    "Worcester": 206518,
    "Springfield": 155929,
    "Quincy": 101636,
    "Lynn": 101253,
    "Brockton": 105643,
}


def population_lookup(town: str) -> int | None:
    """Population for any town the budget cares about (Middlesex set + major
    cities), or None if unknown."""
    geo = TOWN_GEO.get(town)
    if geo:
        return geo[2]
    return EXTRA_TOWN_POP.get(town)


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def towns_within(town: str, radius_miles: float) -> list[str]:
    """Other towns whose centers fall inside the radius, nearest first."""
    if town not in TOWN_GEO:
        return []
    here = TOWN_GEO[town][:2]
    out = [
        (haversine_miles(here, geo[:2]), name)
        for name, geo in TOWN_GEO.items()
        if name != town
    ]
    return [name for d, name in sorted(out) if d <= radius_miles]


def distance_between(town_a: str, town_b: str) -> float | None:
    if town_a not in TOWN_GEO or town_b not in TOWN_GEO:
        return None
    return haversine_miles(TOWN_GEO[town_a][:2], TOWN_GEO[town_b][:2])


def towns_by_population() -> list[str]:
    return [t for t, _ in sorted(TOWN_GEO.items(), key=lambda kv: -kv[1][2])]
