# Middlesex County, Massachusetts municipalities (54)
TOWNS: list[str] = [
    "Acton",
    "Arlington",
    "Ashby",
    "Ashland",
    "Ayer",
    "Bedford",
    "Belmont",
    "Billerica",
    "Boxborough",
    "Burlington",
    "Cambridge",
    "Carlisle",
    "Chelmsford",
    "Concord",
    "Dracut",
    "Dunstable",
    "Everett",
    "Framingham",
    "Groton",
    "Holliston",
    "Hopkinton",
    "Hudson",
    "Lexington",
    "Lincoln",
    "Littleton",
    "Lowell",
    "Malden",
    "Marlborough",
    "Maynard",
    "Medford",
    "Melrose",
    "Natick",
    "Newton",
    "North Reading",
    "Pepperell",
    "Reading",
    "Sherborn",
    "Shirley",
    "Stoneham",
    "Stow",
    "Sudbury",
    "Tewksbury",
    "Townsend",
    "Tyngsborough",
    "Wakefield",
    "Waltham",
    "Watertown",
    "Wayland",
    "Westford",
    "Weston",
    "Wilmington",
    "Winchester",
    "Woburn",
]

# --------------------------------------------------------------------------- #
# HUB ADAPTER ROADMAP H0.1 — canonical primary ZIP + city + state per town.
# --------------------------------------------------------------------------- #
# This is the *seed input* for the ZIP-templated national hubs (Camp Invention,
# Skyhawks/Configio, iD Tech). A wrong seed ZIP silently shifts the whole search
# radius, so each entry is the USPS primary ZIP for that municipality — not an
# inferred/centroid ZIP. All fall inside the MA 014xx–024xx band (validated by
# `validate_town_zips`). `city` is the USPS city name (== town for all 54 here).
TOWN_ZIPS: dict[str, dict[str, str]] = {
    "Acton": {"zip": "01720", "city": "Acton", "state": "MA"},
    "Arlington": {"zip": "02474", "city": "Arlington", "state": "MA"},
    "Ashby": {"zip": "01431", "city": "Ashby", "state": "MA"},
    "Ashland": {"zip": "01721", "city": "Ashland", "state": "MA"},
    "Ayer": {"zip": "01432", "city": "Ayer", "state": "MA"},
    "Bedford": {"zip": "01730", "city": "Bedford", "state": "MA"},
    "Belmont": {"zip": "02478", "city": "Belmont", "state": "MA"},
    "Billerica": {"zip": "01821", "city": "Billerica", "state": "MA"},
    "Boxborough": {"zip": "01719", "city": "Boxborough", "state": "MA"},
    "Burlington": {"zip": "01803", "city": "Burlington", "state": "MA"},
    "Cambridge": {"zip": "02139", "city": "Cambridge", "state": "MA"},
    "Carlisle": {"zip": "01741", "city": "Carlisle", "state": "MA"},
    "Chelmsford": {"zip": "01824", "city": "Chelmsford", "state": "MA"},
    "Concord": {"zip": "01742", "city": "Concord", "state": "MA"},
    "Dracut": {"zip": "01826", "city": "Dracut", "state": "MA"},
    "Dunstable": {"zip": "01827", "city": "Dunstable", "state": "MA"},
    "Everett": {"zip": "02149", "city": "Everett", "state": "MA"},
    "Framingham": {"zip": "01701", "city": "Framingham", "state": "MA"},
    "Groton": {"zip": "01450", "city": "Groton", "state": "MA"},
    "Holliston": {"zip": "01746", "city": "Holliston", "state": "MA"},
    "Hopkinton": {"zip": "01748", "city": "Hopkinton", "state": "MA"},
    "Hudson": {"zip": "01749", "city": "Hudson", "state": "MA"},
    "Lexington": {"zip": "02421", "city": "Lexington", "state": "MA"},
    "Lincoln": {"zip": "01773", "city": "Lincoln", "state": "MA"},
    "Littleton": {"zip": "01460", "city": "Littleton", "state": "MA"},
    "Lowell": {"zip": "01852", "city": "Lowell", "state": "MA"},
    "Malden": {"zip": "02148", "city": "Malden", "state": "MA"},
    "Marlborough": {"zip": "01752", "city": "Marlborough", "state": "MA"},
    "Maynard": {"zip": "01754", "city": "Maynard", "state": "MA"},
    "Medford": {"zip": "02155", "city": "Medford", "state": "MA"},
    "Melrose": {"zip": "02176", "city": "Melrose", "state": "MA"},
    "Natick": {"zip": "01760", "city": "Natick", "state": "MA"},
    "Newton": {"zip": "02458", "city": "Newton", "state": "MA"},
    "North Reading": {"zip": "01864", "city": "North Reading", "state": "MA"},
    "Pepperell": {"zip": "01463", "city": "Pepperell", "state": "MA"},
    "Reading": {"zip": "01867", "city": "Reading", "state": "MA"},
    "Sherborn": {"zip": "01770", "city": "Sherborn", "state": "MA"},
    "Shirley": {"zip": "01464", "city": "Shirley", "state": "MA"},
    "Somerville": {"zip": "02143", "city": "Somerville", "state": "MA"},
    "Stoneham": {"zip": "02180", "city": "Stoneham", "state": "MA"},
    "Stow": {"zip": "01775", "city": "Stow", "state": "MA"},
    "Sudbury": {"zip": "01776", "city": "Sudbury", "state": "MA"},
    "Tewksbury": {"zip": "01876", "city": "Tewksbury", "state": "MA"},
    "Townsend": {"zip": "01469", "city": "Townsend", "state": "MA"},
    "Tyngsborough": {"zip": "01879", "city": "Tyngsborough", "state": "MA"},
    "Wakefield": {"zip": "01880", "city": "Wakefield", "state": "MA"},
    "Waltham": {"zip": "02451", "city": "Waltham", "state": "MA"},
    "Watertown": {"zip": "02472", "city": "Watertown", "state": "MA"},
    "Wayland": {"zip": "01778", "city": "Wayland", "state": "MA"},
    "Westford": {"zip": "01886", "city": "Westford", "state": "MA"},
    "Weston": {"zip": "02493", "city": "Weston", "state": "MA"},
    "Wilmington": {"zip": "01887", "city": "Wilmington", "state": "MA"},
    "Winchester": {"zip": "01890", "city": "Winchester", "state": "MA"},
    "Woburn": {"zip": "01801", "city": "Woburn", "state": "MA"},
}

import re as _re

# MA ZIP band: 010xx–027xx covers the state; the Middlesex set sits in 014xx–024xx.
_MA_ZIP_RE = _re.compile(r"^0(?:1[4-9]|2[0-4])\d{2}$")


def town_seed(town: str) -> dict[str, str] | None:
    """ZIP/city/state seed for one town, or None if not a known Middlesex town."""
    return TOWN_ZIPS.get(town)


def validate_town_zips() -> list[str]:
    """Return a list of validation errors (empty == all 54 ZIPs valid).

    H0.1 acceptance: every geo town (the authoritative 54-municipality set in
    config.town_geo.TOWN_GEO) has a non-empty ZIP that is 5 digits and inside the
    MA 014xx–024xx band. TOWN_GEO is used as the canonical list because the hub
    runner needs both lat/lon (from TOWN_GEO) and a ZIP seed (from here).
    """
    from config.town_geo import TOWN_GEO

    errors: list[str] = []
    for town in TOWN_GEO:
        seed = TOWN_ZIPS.get(town)
        if not seed:
            errors.append(f"{town}: missing from TOWN_ZIPS")
            continue
        z = (seed.get("zip") or "").strip()
        if not z:
            errors.append(f"{town}: empty zip")
        elif not _MA_ZIP_RE.match(z):
            errors.append(f"{town}: zip {z!r} outside MA 014xx-024xx band")
        if (seed.get("state") or "").upper() != "MA":
            errors.append(f"{town}: state != MA")
    return errors
