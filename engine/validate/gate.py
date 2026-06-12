"""The ONE publish gate (plan §8, R6.1). Every program/session passes through
`gate_program` before it can be written; there is no other path to the CSVs.

Checks, in order:
  1. Name integrity        chrome/menu text, filename, bare ID, empty → gap
  2. Info-url invariant    fetched THIS RUN, ≥400 chars, contains program name
  3. Evidence              ≥1 of {summer dates, youth age/grade, camp-scoped
                           catalog provenance}; adult/membership evidence → gap
  4. Register upgrade      enrollment signals may upgrade to parent_ready;
                           failure here NEVER blocks an info_confirmed row
  5. Geo                   out-of-state host/register → gap
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from engine.fetch.urls import normalize_url
from engine.model import Gap, Program, Session
from engine.validate.signals import ADULT_BLOCKER_RE, verify_registrable

MIN_INFO_CHARS = 400  # R4.3

# --- check 1: name integrity (ported CHROME_LABELS idea, extended) -----------

CHROME_LABELS = frozenset(
    {
        "back to top", "skip to main content", "skip to content",
        "skip to cookie notice", "skip to footer", "manage cookies",
        "cookie notice", "accept cookies", "see details", "details",
        "more info", "more information", "learn more", "read more",
        "view all", "view more", "show more", "register", "register here",
        "register now", "register online", "enroll", "enroll now", "sign up",
        "sign up now", "signup", "join waitlist", "join the waitlist",
        "waitlist", "add to cart", "checkout", "click here", "home", "menu",
        "close", "search", "next", "previous", "back", "continue", "submit",
        "login", "log in", "sign in", "my account", "contact", "contact us",
        "referral",
    }
)
_CHROME_PATTERN_RE = re.compile(
    r"^(?:skip to\b.*|back to\b.*|jump to\b.*|toggle\b.*|open\b.*menu|close\b.*menu)$",
    re.I,
)
_FILENAME_RE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|pdf|docx?|xlsx?|css|js)$", re.I)
_BARE_ID_RE = re.compile(r"^[#\-\s]*\d[\d\s\-#]*$")


def bad_name_reason(name: str) -> str | None:
    n = re.sub(r"\s+", " ", (name or "").strip().strip(".:|–-")).lower()
    if not n:
        return "empty name"
    if n in CHROME_LABELS or _CHROME_PATTERN_RE.match(n):
        return f"chrome name: {name!r}"
    if _FILENAME_RE.search(n):
        return f"filename as name: {name!r}"
    if _BARE_ID_RE.match(n):
        return f"bare id as name: {name!r}"
    return None


# --- check 2: info-url invariant ---------------------------------------------

_STOP_TOKENS = {"the", "a", "an", "of", "and", "for", "at", "in", "to", "with", "camp"}


def name_in_text(name: str, text: str) -> bool:
    toks = [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in _STOP_TOKENS]
    if not toks:
        return False
    low = (text or "").lower()
    hits = sum(1 for t in toks if t in low)
    return hits >= max(1, len(toks) - 1)


# --- check 3: evidence (applied to EXTRACTED fields, never raw names — R4.1) --

_SUMMER_DATE_RE = re.compile(
    r"\b(?:jun|jul|aug)[a-z]*\.?\s*\d{1,2}|\b0?[678]/\d{1,2}\b|summer\s+20\d{2}",
    re.I,
)
_MONTH_TOKEN_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\b(\d{1,2})/\d{1,2}\b",
    re.I,
)
_MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}


def is_summer_window(dates: str) -> bool:
    """True when the date evidence is a summer-window program. A range that
    STARTS before June ("April 7th - June 16th" spring clinics) is not summer
    even though a June token appears (Phase-3 live finding)."""
    months: list[int] = []
    for m in _MONTH_TOKEN_RE.finditer(dates or ""):
        if m.group(1):
            months.append(_MONTH_NUM[m.group(1)[:3].lower()])
        elif m.group(2):
            num = int(m.group(2))
            if 1 <= num <= 12:
                months.append(num)
    if not months:
        return bool(re.search(r"summer\s+20\d{2}", dates or "", re.I))
    return months[0] in (6, 7, 8)
_YOUTH_AGE_RE = re.compile(
    r"ages?\s*:?\s*\d|grades?\s*:?\s*(?:[k0-9]|pre)|\bpre-?k\b|kindergart|"
    r"\byouth\b|rising\s+(?:[1-9]|k)",
    re.I,
)
_ADULT_EVIDENCE_RE = re.compile(
    r"\b(?:adults?\s+only|for\s+adults|18\s*\+|21\s*\+|senior|membership|"
    r"men'?s\s+league|women'?s\s+league|fundraiser|donation)\b",
    re.I,
)

# --- check 5: geo (focused port of is_out_of_state_url) -----------------------

_NON_MA_STATES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "michigan", "minnesota", "mississippi", "missouri", "montana",
    "nebraska", "nevada", "new-hampshire", "new-jersey", "new-mexico",
    "new-york", "north-carolina", "north-dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode-island", "south-carolina", "south-dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west-virginia", "wisconsin", "wyoming",
)
_NON_MA_RE = re.compile(
    r"/(?:" + "|".join(_NON_MA_STATES) + r")(?:/|$)"
    r"|/(?:al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|mi|mn|"
    r"ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|"
    r"wa|wv|wi|wy)/(?=[a-z])",
    re.I,
)


def is_out_of_state(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return bool(_NON_MA_RE.search(parsed.path.lower()))


# --- results -------------------------------------------------------------------


@dataclass
class GateResult:
    published: list[Session] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.published)


def gate_program(
    program: Program,
    *,
    fetched_text: dict[str, str],
    provider_id: str = "",
) -> GateResult:
    """Gate every session of a program. `fetched_text` maps url → rendered text
    fetched THIS RUN (the run cache view) — the info-url invariant reads only
    from it; a URL absent from the map was not fetched and cannot publish."""
    pid = provider_id or program.provider_id
    result = GateResult()

    # Check 1 on the program name once; sessions inherit it.
    name_problem = bad_name_reason(program.name)
    if name_problem:
        result.gaps.append(
            Gap(provider_id=pid, reason="needs_review", evidence=name_problem,
                suggested_action="recover a real program name upstream")
        )
        return result

    sessions = program.sessions or [
        Session(name=program.name, info_url=program.info_url)
    ]
    for sess in sessions:
        sess.program_id = sess.program_id or program.program_id
        name = sess.name or program.name

        problem = bad_name_reason(name)
        if problem:
            result.gaps.append(
                Gap(provider_id=pid, reason="needs_review", evidence=problem,
                    suggested_action="fix session name extraction")
            )
            continue

        # 5. Geo (cheap; before fetch-dependent checks)
        if is_out_of_state(sess.info_url) or is_out_of_state(sess.register_url):
            result.gaps.append(
                Gap(provider_id=pid, reason="needs_review",
                    evidence=f"out-of-state url: {sess.info_url or sess.register_url}",
                    suggested_action="confirm geography; drop if not in-state")
            )
            continue

        # 2. Info-url invariant (cache keys are normalized URLs)
        info_key = (
            sess.info_url if sess.info_url in fetched_text else normalize_url(sess.info_url)
        )
        info_text = fetched_text.get(info_key, "")
        if len(info_text) < MIN_INFO_CHARS or not name_in_text(name, info_text):
            why = (
                "info_url not fetched this run" if info_key not in fetched_text
                else f"info page {len(info_text)} chars"
                if len(info_text) < MIN_INFO_CHARS
                else "program name absent from info page"
            )
            result.gaps.append(
                Gap(provider_id=pid, reason="empty" if len(info_text) < MIN_INFO_CHARS else "needs_review",
                    evidence=f"{name}: {why} ({sess.info_url})",
                    suggested_action="render/replace info_url")
            )
            continue
        sess.content_chars = len(info_text)

        # 3. Evidence on extracted fields + camp-scoped provenance
        evidence_blob = " ".join(filter(None, (sess.dates, sess.ages, sess.price)))
        field_evidence = bool(
            (sess.dates and is_summer_window(sess.dates))
            or _YOUTH_AGE_RE.search(evidence_blob)
        )
        # Adult markers in EXTRACTED fields always gap. Page-level adult markers
        # only gap rows with no protective evidence of their own — catalog pages
        # carry "Membership"/account chrome that must not sink real camp rows
        # (Phase-3 live finding: Hayden specialty camps gapped on nav chrome).
        page_adult = _ADULT_EVIDENCE_RE.search(info_text[:4000]) and not _YOUTH_AGE_RE.search(
            evidence_blob + " " + info_text[:4000]
        )
        if _ADULT_EVIDENCE_RE.search(evidence_blob) or (
            page_adult and not field_evidence and not program.camp_scoped
        ):
            result.gaps.append(
                Gap(provider_id=pid, reason="needs_review",
                    evidence=f"{name}: adult/membership evidence",
                    suggested_action="exclude unless youth context confirmed")
            )
            continue
        has_evidence = (
            program.camp_scoped
            or field_evidence
            or bool(_SUMMER_DATE_RE.search(info_text[:4000]))
            or bool(_YOUTH_AGE_RE.search(info_text[:4000]))
        )
        if not has_evidence:
            result.gaps.append(
                Gap(provider_id=pid, reason="needs_review",
                    evidence=f"{name}: no summer/youth/camp-scope evidence",
                    suggested_action="verify program is a youth summer offering")
            )
            continue

        # 4. Register verification — upgrade only, never a blocker.
        verdict = "info_confirmed"
        reg_text = ""
        if sess.register_url:
            reg_text = fetched_text.get(sess.register_url) or fetched_text.get(
                normalize_url(sess.register_url), ""
            )
        check_url = sess.register_url or sess.info_url
        check_text = reg_text or info_text
        sig = verify_registrable(check_url, check_text, context=name)
        if sig.auto_verdict == "parent_ready":
            verdict = "parent_ready"
        sess.verdict = verdict
        sess.evidence = {
            "camp_scoped": program.camp_scoped,
            "dates": sess.dates, "ages": sess.ages, "price": sess.price,
            "signals": sig.to_dict(),
        }
        result.published.append(sess)

    return result
