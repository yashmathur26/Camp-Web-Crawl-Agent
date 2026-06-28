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
from engine.validate.noncamp import (
    adult_min_age,
    display_prefixed_name,
    noncamp_reason,
    sanitize_age,
)
from engine.validate.signals import ADULT_BLOCKER_RE, is_platform_host, verify_registrable

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
_FILENAME_RE = re.compile(r"\.(?:html?|png|jpe?g|gif|svg|webp|pdf|docx?|xlsx?|css|js)$", re.I)
_BARE_ID_RE = re.compile(r"^[#\-\s]*\d[\d\s\-#]*$")
# Phase 1 name-integrity extension: multi-word category/article/landing names
# that name a SECTION or a blog post, never an individual camp.
# High-precision only: these phrases name a SECTION, an article, or an alumni
# page — never an individual camp. (A name merely ENDING in "Program"/"Programs"
# is NOT rejected here — "Summer Business Program" is a real camp; section
# landings are caught by the hub-slug URL check instead.)
_CATEGORY_NAME_RE = re.compile(
    r"^how\s+to\s+\w+"                       # "How To Enroll", "How To Register"
    r"|^programs?$|^activities$|^our\s+programs?$"  # bare section labels only
    r"|\bclass\s+of\s+\d{4}\b"               # alumni "Class of 2024"
    r"|^\d+\s+reasons\b|\bultimate\s+guide\b"  # listicle/article titles
    r"|\bclick\s+here\b|\bview\s+(?:all|more)\b",
    re.I,
)
# Host-echo names ("ussportscamps.com — Camps", "Goddardschool.Com"): a bare
# domain token standing in for a real camp name.
_HOST_ECHO_RE = re.compile(r"\b[\w-]+\.(?:com|org|net|edu|gov|us|io)\b", re.I)


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
    if _HOST_ECHO_RE.search(n):
        return f"host-echo name: {name!r}"
    if _CATEGORY_NAME_RE.search(n):
        return f"category/article name: {name!r}"
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
    r"\byouth\b|rising\s+(?:[1-9]|k)|preschool|toddler",
    re.I,
)
_ADULT_EVIDENCE_RE = re.compile(
    r"\b(?:adults?\s+only|for\s+adults|18\s*\+|21\s*\+|senior|membership|"
    r"men'?s\s+league|women'?s\s+league|fundraiser|donation)\b",
    re.I,
)
# Adult fitness-class language (ported from the old pipeline's _ADULT_FITNESS_RE
# after the "Active Agers" leak): blocks only with ZERO youth signals, since
# kids' yoga/dance camps exist. Requires >=2 distinct markers to avoid a single
# incidental word ("dance") sinking a real camp.
_ADULT_FITNESS_RE = re.compile(
    r"\b(yoga|pilates|zumba|aerobics|cardio(?:vascular)?|strength|crossfit|"
    r"boot\s*camp|pickleball|personal\s+train\w+|group\s+fitness|"
    r"muscle\s+conditioning|bone\s+health|tai\s+chi)\b",
    re.I,
)


def _adult_fitness_page(info_text: str, youth_blob: str) -> bool:
    hits = set(m.group(1).lower() for m in _ADULT_FITNESS_RE.finditer(info_text[:4000]))
    return len(hits) >= 2 and not _YOUTH_AGE_RE.search(youth_blob)

# Clinical/therapeutic context (MGH Aspire finding): hospital group programs
# describe themselves in treatment vocabulary no camp page uses. >=2 distinct
# markers on a non-camp-scoped page -> not a camp (re-categorize if the operator
# adds therapeutic programs later).
_CLINICAL_RE = re.compile(
    r"\b(clinic(?:al|ian)|therap\w+|intervention|diagnos\w+|referral|"
    r"patients?|psychiat\w+|outpatient|treatment|social\s+work)\b",
    re.I,
)


def _clinical_page(info_text: str) -> bool:
    hits = {m.group(1).lower()[:7] for m in _CLINICAL_RE.finditer(info_text[:5000])}
    return len(hits) >= 2


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


# --- Phase 1: host denylist + same-host rule + hub-slug reject ----------------
# Hard-deny hosts/paths (lifted from the proposer's _DENY_HOST_RE and expanded):
# third-party aggregators, admissions blogs, parent-paper directories, and the
# tag/category archive paths that masquerade as program pages. A row whose
# info/register URL matches these is never a provider's own camp page — gap it.
_DENY_HOST_RE = re.compile(
    r"facebook|instagram|youtube|twitter|x\.com|yelp|tripadvisor|"
    r"activityhero|macaronikid|mommypoppins|care\.com|niche\.com|yellowpages|"
    r"collegevine|parentspaper|parents?paper|parent(?=\w*\.(?:com|net|org))|"
    r"(?:^|\.)blog\.|\bblogspot\b|wordpress\.com",
    re.I,
)
_DENY_PATH_RE = re.compile(r"/(?:tag|category|tags|categories|author)/", re.I)


def is_denylisted(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return bool(_DENY_HOST_RE.search(host) or _DENY_PATH_RE.search(parsed.path.lower()))


# Hub / category / landing slugs the crawler descends FROM — a section overview,
# not an individual camp. Matched on the URL's leaf path.
_HUB_SLUG_RE = re.compile(
    r"^/?(?:camps?|summer-?camps?|programs?|all-?camps?|our-?camps?|"
    r"how-to-(?:enroll|register)|registration|enroll|camp-directory|"
    r"activities|classes|offerings)/?$",
    re.I,
)


def is_hub_slug(url: str) -> bool:
    path = urlparse(url or "").path.rstrip("/")
    if not path:
        return False
    leaf = "/" + path.split("/")[-1]
    return bool(_HUB_SLUG_RE.match(leaf))


def _host_of(url_or_host: str) -> str:
    """Host from a full URL or a bare host string."""
    s = (url_or_host or "").strip()
    if "//" in s:
        return urlparse(s).netloc.lower()
    return urlparse(f"//{s}").netloc.lower()


def _registrable_domain(url_or_host: str) -> str:
    host = _host_of(url_or_host).split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def same_registrable_domain(a: str, b: str) -> bool:
    da, db = _registrable_domain(a), _registrable_domain(b)
    return bool(da) and da == db


# --- results -------------------------------------------------------------------


@dataclass
class GateResult:
    published: list[Session] = field(default_factory=list)  # confirmed tier
    review: list[Session] = field(default_factory=list)     # human-markup tier
    gaps: list[Gap] = field(default_factory=list)           # diagnosed, not published

    @property
    def ok(self) -> bool:
        return bool(self.published)


# Weak name provenance: a slug / link-text / model-derived name is not trustworthy
# enough for the confirmed tier on its own (plan Phase 5 — "trust name_source").
_WEAK_NAME_SOURCES = {"slug", "link_text", "link", "llm", "fallback"}


def gate_program(
    program: Program,
    *,
    fetched_text: dict[str, str],
    provider_id: str = "",
    provider_name: str = "",
    provider_host: str = "",
    include_review: bool = True,  # retained for call-site compat; review tier is
                                  # always populated now (slop → review, not gap)
) -> GateResult:
    """Gate every session of a program into three tiers: confirmed (published),
    review (thin-evidence / off-domain / unresolved — a separate human-markup
    file), or gap (diagnosed, not published). `fetched_text` maps url → rendered
    text fetched THIS RUN (the run cache view); a URL absent from it was not
    fetched and cannot publish. The gate is the ONE keep/drop writer (R6)."""
    pid = provider_id or program.provider_id
    result = GateResult()

    def _gap(reason: str, evidence: str, action: str) -> None:
        result.gaps.append(Gap(provider_id=pid, reason=reason, evidence=evidence,
                               suggested_action=action))

    def _to_review(sess: Session, why: str) -> None:
        sess.verdict = "needs_review"
        sess.evidence = {"review_reason": why, "dates": sess.dates,
                         "ages": sess.ages, "price": sess.price}
        if not sess.raw_name:
            sess.raw_name = sess.name
        sess.display_name = display_prefixed_name(sess.name, provider_name)
        result.review.append(sess)

    # Check 1 on the program name once; a bad program name is recoverable slop
    # (chrome/category/host-echo) — route to review, never silently drop.
    name_problem = bad_name_reason(program.name)
    if name_problem:
        _to_review(
            Session(name=program.name, info_url=program.info_url,
                    program_id=program.program_id), name_problem,
        )
        return result

    sessions = program.sessions or [
        Session(name=program.name, info_url=program.info_url)
    ]
    for sess in sessions:
        sess.program_id = sess.program_id or program.program_id
        name = sess.name or program.name

        # 1. Name integrity — chrome/filename/bare-id/host-echo/category → review.
        problem = bad_name_reason(name)
        if problem:
            _to_review(sess, problem)
            continue

        # 5. Geo (cheap; before fetch-dependent checks)
        if is_out_of_state(sess.info_url) or is_out_of_state(sess.register_url):
            _gap("needs_review",
                 f"out-of-state url: {sess.info_url or sess.register_url}",
                 "confirm geography; drop if not in-state")
            continue

        # 1b. Host denylist (hard pre-check, R: lifted from the proposer): a
        # third-party aggregator / admissions blog / tag-archive is never a
        # provider's own camp page — gap it before anything else fetch-dependent.
        if is_denylisted(sess.info_url) or is_denylisted(sess.register_url):
            _gap("needs_review",
                 f"{name}: denylisted host/path ({sess.info_url or sess.register_url})",
                 "third-party aggregator/blog/tag page; exclude")
            continue

        # 1c. Hub / category / landing page: a section overview the crawler
        # descended FROM (/camps, /summer-camps, /programs, /how-to-enroll), not
        # an individual camp. Route to review.
        if is_hub_slug(sess.info_url):
            _to_review(sess, f"hub/landing page (not an individual camp): {sess.info_url}")
            continue

        # 1d. Same-host rule for GENERIC-path rows: a generic guess may publish to
        # confirmed only if its info_url shares the provider's registrable domain
        # (or is a known registration platform tied to the provider). Off-domain
        # generic rows → review. Vendor adapters (own platform hosts) are exempt.
        if (
            sess.extractor == "generic" and provider_host
            and not is_platform_host(sess.info_url)
            and not same_registrable_domain(sess.info_url, provider_host)
        ):
            _to_review(
                sess,
                f"off-domain generic row (info host not {provider_host}): {sess.info_url}",
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
            _gap("empty" if len(info_text) < MIN_INFO_CHARS else "needs_review",
                 f"{name}: {why} ({sess.info_url})", "render/replace info_url")
            continue
        sess.content_chars = len(info_text)

        # Sanitize garbage age artifacts ("age 02", "ages 1") before they can
        # display or count as youth evidence (Waltham resource-page finding).
        sess.ages = sanitize_age(sess.ages)

        # 2c. Page role (Phase 3): an about/alumni/news/logistics page the feature
        # classifier marked `peripheral` is not this camp's page — out of confirmed,
        # into review (uncertainty → review). Vendor rows carry no role (skip).
        if sess.page_role == "peripheral":
            _to_review(sess, "page role: peripheral (about/alumni/news/logistics)")
            continue

        # 2b. Non-camp category gate (recruitment, lessons/open-play, resource
        # pages, school-district services, year-round childcare). Domain-agnostic;
        # fires even when the row carries an incidental summer date or youth grade
        # (the failure mode the Waltham list exposed). → review.
        summer_now = bool((sess.dates or "").strip() and is_summer_window(sess.dates))
        nc = noncamp_reason(
            name, info_url=sess.info_url, register_url=sess.register_url,
            text=info_text, dates=sess.dates, is_summer=summer_now,
        )
        if nc:
            _to_review(sess, nc)
            continue

        # 3. Evidence on extracted fields + camp-scoped provenance
        evidence_blob = " ".join(filter(None, (sess.dates, sess.ages, sess.price)))
        field_evidence = bool(
            (sess.dates and is_summer_window(sess.dates))
            or _YOUTH_AGE_RE.search(evidence_blob)
        )
        # Adult markers in EXTRACTED fields always reject. Page-level adult markers
        # only reject rows with no protective evidence of their own — catalog pages
        # carry "Membership"/account chrome that must not sink real camp rows
        # (Phase-3 live finding: Hayden specialty camps gapped on nav chrome).
        page_adult = _ADULT_EVIDENCE_RE.search(info_text[:4000]) and not _YOUTH_AGE_RE.search(
            evidence_blob + " " + info_text[:4000]
        )
        # AUDIENCE adult markers ("for adults", "adults only", 18+/21+) state who
        # the program is FOR — they reject even when summer dates exist (the
        # Symphony's adults-only July camp). Chrome markers (membership/senior
        # nav) still need the no-evidence condition.
        page_adult_audience = re.search(
            r"\bfor\s+adults?\b|\badults?\s+only\b|\b(?:18|21)\s*\+", info_text[:4000], re.I
        ) and not _YOUTH_AGE_RE.search(evidence_blob + " " + info_text[:4000])
        # Adult lower bound in the extracted age field — incl. a bare "19+"
        # (Masters Swim finding) and "ages 18-99", excl. "18 months".
        is_adult_min_age = adult_min_age(sess.ages)
        if is_adult_min_age or _ADULT_EVIDENCE_RE.search(evidence_blob) or page_adult_audience or (
            page_adult and not field_evidence and not program.camp_scoped
        ) or (
            not program.camp_scoped
            and _adult_fitness_page(info_text, evidence_blob + " " + info_text[:4000])
        ):
            _to_review(sess, "adult/membership evidence")
            continue
        if not program.camp_scoped and _clinical_page(info_text):
            _gap("needs_review",
                 f"{name}: clinical/therapeutic program context",
                 "not a camp; revisit if therapeutic category added")
            continue
        # Off-season: a row whose OWN dates are non-summer is out of scope now
        # (operator decision: Winter/April clinics, Fall leagues return later).
        if (sess.dates or "").strip() and not is_summer_window(sess.dates):
            _to_review(sess, f"off-season dates ({sess.dates})")
            continue
        # Evidence must live in the row's OWN extracted fields (or camp scope).
        # Page-level word scans let every rec-center page "mention June" and
        # published Tai Chi/Arthritis rows (operator feedback round 2). → review.
        has_evidence = program.camp_scoped or field_evidence
        if not has_evidence:
            _to_review(sess, "no summer/youth/camp-scope evidence")
            continue

        # 3b. Weak-source name with no real identity (single-token slug/link
        # name like "Homeschool") doesn't enter confirmed without cleanup — route
        # to review for normalization (plan Phase 5).
        if sess.name_source in _WEAK_NAME_SOURCES and len(name.split()) <= 1:
            _to_review(sess, f"weak-source name needs cleanup ({sess.name_source})")
            continue

        # 4. Register verification + confidence → verdict ceiling (v3 Phase 2).
        from engine.extract.register import verdict_ceiling
        from engine.validate.signals import is_registration_platform_url

        evidence_clean = bool(field_evidence or program.camp_scoped)
        reg_text = ""
        if sess.register_url:
            reg_text = fetched_text.get(sess.register_url) or fetched_text.get(
                normalize_url(sess.register_url), ""
            )
        check_url = sess.register_url or sess.info_url
        check_text = reg_text or info_text
        sig = verify_registrable(check_url, check_text, context=name)

        if sess.register_confidence:
            # The Phase 2 resolver already tiered the link; apply its ceiling.
            verdict = verdict_ceiling(sess.register_confidence, evidence_clean=evidence_clean)
        else:
            # Vendor / non-generic rows: keep the proven verify_registrable upgrade.
            verdict = "parent_ready" if sig.auto_verdict == "parent_ready" else "info_confirmed"
            # A known-platform item page that IS the booking page (WebTrac iteminfo,
            # register_url == info_url) is a GENUINE combined page, not the old
            # aliasing bug — mark it so §2.2.2's regression alarm stays quiet.
            if (sess.register_url and is_registration_platform_url(sess.register_url)
                    and normalize_url(sess.register_url) == normalize_url(sess.info_url)):
                sess.register_is_info = True
                sess.register_confidence = "high"

        # A medium/low resolution that didn't clear the bar is a doubtful signup —
        # route to review (uncertainty → review, never silent publish/drop).
        if verdict == "needs_review":
            _to_review(sess, f"register confidence {sess.register_confidence}: needs human check")
            continue

        sess.verdict = verdict
        # Name accuracy (plan Phase 5): keep the bare IDENTITY name in `name`
        # (dedupe + eval match on it); the parent-facing, provider-prefixed label
        # goes in display_name; raw_name preserves the original for audit.
        if not sess.raw_name:
            sess.raw_name = sess.name
        sess.display_name = display_prefixed_name(sess.name, provider_name)
        sess.evidence = {
            "camp_scoped": program.camp_scoped,
            "dates": sess.dates, "ages": sess.ages, "price": sess.price,
            "name_source": sess.name_source,
            "register_confidence": sess.register_confidence,
            "register_is_info": sess.register_is_info,
            "signals": sig.to_dict(),
        }
        result.published.append(sess)

    return result
