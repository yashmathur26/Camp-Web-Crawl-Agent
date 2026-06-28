"""HUB ADAPTER ROADMAP H0.4 — canonical session identity (the dedup key).

The single most important accuracy primitive: every emitted row gets a stable
`session_uid` so the same camp discovered via two paths (e.g. a Burlington
Skyhawks flag-football camp that is *also* a Burlington WebTrac row) collapses
to one.

Precedence for `session_uid`:
  1. A known platform stable id, when the row resolves to one:
       WebTrac  FMID            (myvscloud iteminfo)
       MyRec    ProgramID       (program_details.aspx)
       Configio Course # / /pd/{id}
       ActiveNet activity id
  2. Else a fuzzy key: (token-set-normalized name, venue_zip, start_date).

Two rows MATCH if their precedence-1 ids are equal, OR their fuzzy keys share
venue_zip + start_date AND name token-set ratio >= FUZZY_THRESHOLD (92).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from rapidfuzz import fuzz

from shared.urls import normalize_url, register_platform_id

FUZZY_THRESHOLD = 92

# Configio detail/cart pages: /pd/{product_id}/{slug}
_CONFIGIO_PD_RE = re.compile(r"/pd/(\d+)", re.I)
# Configio Course # token, e.g. SSA69376
_CONFIGIO_COURSE_RE = re.compile(r"\b([A-Z]{2,4}\d{3,7})\b")
# ActiveNet activity ids appear as activity_id / activityId / .../activity/{id}
_ACTIVENET_HOST_RE = re.compile(r"activecommunities\.com|activityreg\.com", re.I)
_ACTIVENET_PATH_ID_RE = re.compile(r"/activity/(?:search/)?(\d+)", re.I)
# Camp Invention program registration ids: /program-search/camp-invention/{st}/{regid}
_CAMP_INVENTION_RE = re.compile(r"/program-search/[^/]+/([^/]+)/([^/?#]+)", re.I)


def stable_platform_id(url: str, *, course_no: str = "") -> str:
    """A stable cross-path id for the registration URL, or "" if none.

    Builds on shared.urls.register_platform_id (WebTrac FMID / MyRec ProgramID) and
    adds Configio (Course # or /pd/{id}) and ActiveNet activity ids.
    """
    if not url:
        return ""
    # WebTrac FMID / MyRec ProgramID (canonicalize first so query order/tracking
    # params don't defeat the lookup).
    from shared.urls import canonical_register_url

    base = register_platform_id(canonical_register_url(url)) or register_platform_id(url)
    if base:
        return base

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    if "configio.com" in host or "skyhawks.com" in host:
        if course_no:
            cm = _CONFIGIO_COURSE_RE.search(course_no.upper())
            if cm:
                return f"configio|course|{cm.group(1)}"
        pd = _CONFIGIO_PD_RE.search(parsed.path)
        if pd:
            return f"configio|pd|{pd.group(1)}"

    if "invent.org" in host:
        m = _CAMP_INVENTION_RE.search(parsed.path)
        if m:
            return f"camp_invention|{m.group(1)}|{m.group(2)}"

    if _ACTIVENET_HOST_RE.search(host):
        qs = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
        for key in ("activity_id", "activityid", "actid"):
            if qs.get(key):
                return f"activenet|activity|{qs[key][0]}"
        m = _ACTIVENET_PATH_ID_RE.search(parsed.path)
        if m:
            return f"activenet|activity|{m.group(1)}"

    # Course # alone (no recognizable host) is still a strong id.
    if course_no:
        cm = _CONFIGIO_COURSE_RE.search(course_no.upper())
        if cm:
            return f"configio|course|{cm.group(1)}"
    return ""


def normalize_name(name: str) -> str:
    """Token-set normalize: lowercase, strip punctuation, sort unique tokens."""
    tokens = re.findall(r"[a-z0-9]+", (name or "").lower())
    return " ".join(sorted(set(tokens)))


def fuzzy_key(name: str, venue_zip: str, start_date: str) -> tuple[str, str, str]:
    return (normalize_name(name), (venue_zip or "").strip(), (start_date or "").strip()[:10])


def _row_id(row: dict) -> str:
    return stable_platform_id(
        row.get("register_url", "") or row.get("info_url", ""),
        course_no=row.get("course_no", "") or row.get("course", ""),
    )


def session_uid(row: dict) -> str:
    """Stable identity string for a row. Precedence-1 id, else a fuzzy key."""
    pid = _row_id(row)
    if pid:
        return pid
    name, zip_, date = fuzzy_key(
        row.get("name", ""),
        row.get("geo_zip", "") or row.get("venue_zip", ""),
        row.get("start_date", "") or row.get("dates", ""),
    )
    return f"fuzzy|{name}|{zip_}|{date}"


def rows_match(a: dict, b: dict) -> bool:
    """True when two rows denote the same real session (H0.4 rule)."""
    ida, idb = _row_id(a), _row_id(b)
    if ida and idb:
        return ida == idb
    # Fuzzy path: require same venue_zip + same start_date + high name ratio.
    ka = fuzzy_key(a.get("name", ""), a.get("geo_zip", "") or a.get("venue_zip", ""),
                   a.get("start_date", "") or a.get("dates", ""))
    kb = fuzzy_key(b.get("name", ""), b.get("geo_zip", "") or b.get("venue_zip", ""),
                   b.get("start_date", "") or b.get("dates", ""))
    if not ka[0] or not kb[0]:
        return False
    if ka[1] != kb[1] or ka[2] != kb[2]:
        return False
    if not ka[1] or not ka[2]:
        # Without a venue_zip AND a start_date we will not fuzzy-merge — too risky.
        return False
    return fuzz.token_set_ratio(ka[0], kb[0]) >= FUZZY_THRESHOLD


def _merge(into: dict, other: dict) -> dict:
    """Merge `other` into `into` in place: fill blanks, union provenance/towns."""
    for k, v in other.items():
        if k in ("discovered_via", "serving_towns"):
            continue
        if not into.get(k) and v:
            into[k] = v
    via = list(dict.fromkeys(
        (into.get("discovered_via") or [])
        + (other.get("discovered_via") or [])
        + ([other["platform"]] if other.get("platform") else [])
    ))
    into["discovered_via"] = via
    towns = list(dict.fromkeys(
        (into.get("serving_towns") or []) + (other.get("serving_towns") or [])
    ))
    if towns:
        into["serving_towns"] = towns
    return into


def dedupe_sessions(rows: list[dict]) -> tuple[list[dict], int]:
    """Collapse rows that denote the same session. Returns (deduped, removed).

    Each kept row gets a `session_uid`, a `discovered_via` provenance list, and a
    merged `serving_towns` list. `removed` is the count of collapsed duplicates
    (reported in the run log per H2.5 / H4.2).
    """
    kept: list[dict] = []
    removed = 0
    for row in rows:
        row = dict(row)
        if not row.get("discovered_via") and row.get("platform"):
            row["discovered_via"] = [row["platform"]]
        match = None
        # Fast path: exact stable-id bucket.
        rid = _row_id(row)
        if rid:
            for k in kept:
                if _row_id(k) == rid:
                    match = k
                    break
        if match is None:
            for k in kept:
                if rows_match(k, row):
                    match = k
                    break
        if match is not None:
            _merge(match, row)
            removed += 1
        else:
            row["session_uid"] = session_uid(row)
            kept.append(row)
    return kept, removed
