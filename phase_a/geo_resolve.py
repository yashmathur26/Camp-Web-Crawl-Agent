"""HUB ADAPTER ROADMAP H0.5 — geo from the venue, never the seed.

Hard rule for all hubs: the authoritative geo tag is the **venue address parsed
from the listing**, never the search ZIP and never the registration domain.

Verified live: a 02421 (Lexington) + 10mi Skyhawks search returned ZERO
Lexington camps — the hits were in Wayland, Watertown, Carlisle, Concord,
Billerica, Burlington. So the seed ZIP is a *search origin*, not a location.

This module:
  - parses a venue address blob into (city, state, zip),
  - maps a venue to its nearest Middlesex town (by ZIP, else by name),
  - exposes `is_ma_venue` / `geo_tag` so the orchestrator can keep only MA camps
    and stamp each kept row with geo_town/geo_zip/geo_state and geo_source="venue".
"""

from __future__ import annotations

import re

from config.town_geo import TOWN_GEO

# ZIP anywhere in an address blob.
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
# ", MA" / ", Massachusetts" / " MA 0xxxx"
_STATE_RE = re.compile(r",?\s*\b([A-Z]{2})\b(?:\s+\d{5})?|,\s*(Massachusetts)\b", re.I)
# US state abbreviations (for explicit non-MA detection).
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

# MA ZIP band: 010xx–027xx.
_MA_ZIP_RE = re.compile(r"^0(?:1\d|2[0-7])\d{2}$")

# Full state name -> 2-letter abbrev (sources like Algolia return "Massachusetts").
_STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


def normalize_state(s: str) -> str:
    """Return a 2-letter state code from an abbrev or full name ('' if unknown)."""
    s = (s or "").strip()
    if not s:
        return ""
    if len(s) == 2 and s.upper() in _US_STATES:
        return s.upper()
    return _STATE_NAME_TO_ABBR.get(s.lower(), s.upper() if len(s) == 2 else "")

# ZIP -> Middlesex town, built once from config.towns.TOWN_ZIPS.
def _zip_to_town() -> dict[str, str]:
    from config.towns import TOWN_ZIPS

    return {v["zip"]: t for t, v in TOWN_ZIPS.items()}


_ZIP_TOWN = _zip_to_town()
_NAME_TOWN = {t.lower(): t for t in TOWN_GEO}


def parse_venue(blob: str) -> dict:
    """Best-effort (city, state, zip) from a free-text venue/address blob."""
    text = " ".join((blob or "").split())
    zip_ = ""
    m = _ZIP_RE.search(text)
    if m:
        zip_ = m.group(1)

    state = ""
    for sm in _STATE_RE.finditer(text):
        cand = (sm.group(1) or sm.group(2) or "").upper()
        if cand in _US_STATES:
            state = cand
            break
    if not state:
        # full state names ("Massachusetts", "New Hampshire", ...)
        low = text.lower()
        for name, abbr in _STATE_NAME_TO_ABBR.items():
            if re.search(r"\b" + re.escape(name) + r"\b", low):
                state = abbr
                break
    if not state and zip_ and _MA_ZIP_RE.match(zip_):
        state = "MA"

    # City: token(s) immediately before ", ST" if present.
    city = ""
    cm = re.search(r"([A-Za-z][A-Za-z .'\-]+?),\s*(?:[A-Z]{2}\b|Massachusetts\b)", text)
    if cm:
        city = cm.group(1).strip()
    return {"city": city, "state": state, "zip": zip_}


def venue_state(blob: str) -> str:
    return parse_venue(blob).get("state", "")


def is_ma_venue(blob: str) -> bool:
    """True only on positive MA evidence (MA token or an MA-band ZIP).

    Asymmetric: an address with an explicit non-MA state token is False; an
    address with no parseable state AND no ZIP is False (we do not assume MA).
    """
    v = parse_venue(blob)
    if v["state"] == "MA":
        return True
    if v["state"] and v["state"] != "MA":
        return False
    if v["zip"] and _MA_ZIP_RE.match(v["zip"]):
        return True
    return False


def resolve_town(blob: str) -> str:
    """Map a venue to a Middlesex town: by ZIP first, then by city name."""
    v = parse_venue(blob)
    if v["zip"] and v["zip"] in _ZIP_TOWN:
        return _ZIP_TOWN[v["zip"]]
    if v["city"] and v["city"].lower() in _NAME_TOWN:
        return _NAME_TOWN[v["city"].lower()]
    return ""


def geo_tag(row: dict) -> dict:
    """Stamp a row with venue-derived geo. Returns a NEW dict.

    Reads from row['venue'] (free-text address) and/or explicit
    row['venue_city']/['venue_state']/['venue_zip'] fields if an adapter already
    structured them. Sets geo_town/geo_city/geo_state/geo_zip and
    geo_source='venue'. Never reads the seed ZIP.
    """
    out = dict(row)
    blob = " ".join(
        str(row.get(k, ""))
        for k in ("venue", "venue_city", "venue_state", "venue_zip", "city", "state")
        if row.get(k)
    )
    parsed = parse_venue(blob)
    city = row.get("venue_city") or parsed["city"]
    state = normalize_state(row.get("venue_state") or parsed["state"] or "")
    zip_ = row.get("venue_zip") or parsed["zip"]
    if not state and zip_ and _MA_ZIP_RE.match(zip_):
        state = "MA"
    out["geo_city"] = city
    out["geo_state"] = state
    out["geo_zip"] = zip_
    out["geo_town"] = resolve_town(blob)
    out["geo_source"] = "venue"
    return out


def keep_if_ma(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split geo-tagged rows into (ma, rejected). Each row is geo_tag'd first."""
    ma: list[dict] = []
    rejected: list[dict] = []
    for row in rows:
        tagged = geo_tag(row)
        blob = " ".join(
            str(row.get(k, ""))
            for k in ("venue", "venue_city", "venue_state", "venue_zip", "city", "state")
            if row.get(k)
        )
        if tagged.get("geo_state") == "MA" or is_ma_venue(blob):
            ma.append(tagged)
        else:
            tagged["_geo_reject"] = f"venue not MA ({tagged.get('geo_state') or 'unknown'})"
            rejected.append(tagged)
    return ma, rejected
