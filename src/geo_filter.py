"""Reject out-of-state and non-local provider URLs for Massachusetts-focused discovery."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# US state abbreviations except Massachusetts (lowercase).
_NON_MA_STATE_ABBREVS: tuple[str, ...] = (
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
    "ks", "ky", "la", "me", "md", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm",
    "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va",
    "wa", "wv", "wi", "wy", "dc",
)

_NON_MA_STATE_NAMES: tuple[str, ...] = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas",
    "utah", "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",
)

_NON_MA_ABBREV_ALT = "|".join(_NON_MA_STATE_ABBREVS)
_NON_MA_NAME_ALT = "|".join(re.escape(n) for n in _NON_MA_STATE_NAMES)

# Host substrings that are never MA youth-camp providers for our pipeline.
_OUT_OF_STATE_HOST_MARKERS: tuple[str, ...] = (
    "lexingtonky.",
    "lexingtonymca.com",
    "ymcacky.",
    "jewishva.",
    "jccmilwaukee.",
    "cityoflex.com",
    "jccpgh.",
    "jccpghdaycamps.",
    "jccnh.",
    "ondessonk.",
    "burlingtony.org",  # Burlington Area YMCA (Vermont)
)

# Municipal *.st.gov where st is a US state abbreviation other than MA.
_NON_MA_STATE_GOV_HOST_RE = re.compile(
    rf"^(?:www\.)?.+?(?P<st>{_NON_MA_ABBREV_ALT})\.gov$",
    re.I,
)

# City name embeds state before TLD: burlingtonnc.gov, lexingtonky.gov, townct.myrec.com
_EMBEDDED_STATE_HOST_RE = re.compile(
    rf"^(?:www\.)?[a-z0-9\-]{{2,}}(?P<st>{_NON_MA_ABBREV_ALT})(?:\.gov|\.myrec\.com|\.us)$",
    re.I,
)

# myrec.com subdomains with trailing state token: burlingtonnj.myrec.com
_MYREC_STATE_HOST_RE = re.compile(
    rf"^(?:www\.)?.+?\.(?P<st>{_NON_MA_ABBREV_ALT})\.myrec\.com$",
    re.I,
)

# National trade associations / finders — not a town's registrable camp source.
_NATIONAL_INDEX_HOSTS: frozenset[str] = frozenset({
    "acacamps.org",
    "jcca.org",
    "ymca.org",
    "bgca.org",
    "find.acacamps.org",
    "connect.acacamps.org",
})

# Title/snippet: ", Vermont" / ", VT" / ", North Carolina" etc. (any state except MA).
_TEXT_COMMA_STATE_RE = re.compile(
    rf",\s*(?P<st>{_NON_MA_ABBREV_ALT}|{_NON_MA_NAME_ALT})\b",
    re.I,
)

# Residual high-signal regional phrases not caught by comma-state.
_TEXT_OUT_OF_STATE: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bcentral kentucky\b", re.I), "Central Kentucky"),
    (re.compile(r"\bnorthern virginia\b|\bjcc of northern virginia\b", re.I), "Northern Virginia"),
    (re.compile(r"\bmilwaukee\b.*\bjcc\b|\bjcc\b.*\bmilwaukee\b", re.I), "Milwaukee JCC"),
    (re.compile(r"\bgreater pittsburgh\b|\bpittsburgh,\s*pa\b", re.I), "Greater Pittsburgh"),
    (re.compile(r"\bjewish community center of greater pittsburgh\b", re.I), "Pittsburgh JCC"),
    (re.compile(r"\bgreater new haven\b", re.I), "Greater New Haven, CT"),
    (re.compile(r"\bjcc of greater new haven\b", re.I), "JCC of Greater New Haven, CT"),
    (re.compile(r"\bcamp ondessonk\b", re.I), "Camp Ondessonk (Midwest)"),
)

_MA_LOCATION_RE = re.compile(
    r"\b(?:massachusetts|,?\s*ma\b|,\s*ma\b|\bma\s+0\d{3}\b)",
    re.I,
)


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _host_indicates_non_ma(host: str) -> tuple[bool, str]:
    for marker in _OUT_OF_STATE_HOST_MARKERS:
        if marker in host:
            return True, f"out-of-state host ({marker.rstrip('.')})"

    gov_match = _NON_MA_STATE_GOV_HOST_RE.match(host)
    if gov_match:
        st = gov_match.group("st").lower()
        return True, f"out-of-state municipal host (.{st}.gov)"

    embedded = _EMBEDDED_STATE_HOST_RE.match(host)
    if embedded:
        st = embedded.group("st").lower()
        return True, f"out-of-state host (city+{st} in hostname)"

    myrec = _MYREC_STATE_HOST_RE.match(host)
    if myrec:
        st = myrec.group("st").lower()
        return True, f"out-of-state MyRec host (.{st}.myrec.com)"

    return False, ""


def _text_indicates_non_ma(combined: str) -> tuple[bool, str]:
    if _MA_LOCATION_RE.search(combined):
        return False, ""

    match = _TEXT_COMMA_STATE_RE.search(combined)
    if match:
        label = match.group("st").strip()
        return True, f"location text ({label})"

    for pattern, reason in _TEXT_OUT_OF_STATE:
        if pattern.search(combined):
            return True, reason

    return False, ""


def is_national_camp_index(url: str) -> tuple[bool, str]:
    """National camp finder / trade association — skip deep crawl."""
    host = _host(url)
    if not host:
        return False, ""
    if host in _NATIONAL_INDEX_HOSTS or host.endswith(".acacamps.org"):
        return True, "national camp index (not a local provider)"
    return False, ""


def is_out_of_state_url(
    url: str,
    *,
    title: str = "",
    snippet: str = "",
    state: str = "MA",
) -> tuple[bool, str]:
    """Return (True, reason) when a URL is clearly outside the target state."""
    if state != "MA":
        return False, ""

    host = _host(url)
    if not host:
        return False, ""

    national, national_reason = is_national_camp_index(url)
    if national:
        return True, national_reason

    host_oos, host_reason = _host_indicates_non_ma(host)
    if host_oos:
        return True, host_reason

    combined = " ".join((url, title, snippet)).strip()
    if not combined:
        return False, ""

    text_oos, text_reason = _text_indicates_non_ma(combined)
    if text_oos:
        return True, text_reason

    return False, ""


def should_skip_ma_provider(
    url: str,
    *,
    title: str = "",
    snippet: str = "",
) -> tuple[bool, str]:
    """True when a provider seed should not be crawled for an MA town run."""
    return is_out_of_state_url(url, title=title, snippet=snippet, state="MA")
