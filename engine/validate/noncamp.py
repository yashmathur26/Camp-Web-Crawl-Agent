"""Non-camp classifier (operator feedback round — Waltham W3W list).

ONE domain-agnostic question for the gate: given a session's name + URLs (+ the
fetched page text), is this clearly NOT a youth summer camp? It catches the
categories the Waltham list surfaced that slipped past the evidence checks
because they carry incidental youth/summer/date tokens:

  - recruitment / job postings        ("Day Camp Counselors", /join-our-team)
  - recurring lessons / open-gym /     ("Open Play Hours", "Pre-Swim Club",
    drop-in / club activities           "Adaptive ... Swim Lessons", "Masters Swim")
  - resource & document pages          (a foundation's "Periodic Table" PDF,
                                         /camp-resources/, blog/news)
  - year-round childcare / early-       (Springfield JCC "Early Learning Center",
    learning centers                     "ages 6 weeks to 5 years", year-round)
  - school-district service pages       (ESL program, Farm-to-School, Transition
                                         & STRIVE, enrollment/change-of-address)

Every rule is keyword/structure based — NO hard-coded domains — so the next
site in the same category is caught without a code change. Where a category can
legitimately live inside a real camp (a preschool CAMP, a swim CAMP), the rule
fires only when the disqualifying signal appears AND there is no camp signal.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# A genuine camp signal in the *name* protects rules that could otherwise sink a
# real camp (e.g. "Junior Swim Camp" must survive the lessons rule). "boot camp"
# is excluded — it is the fitness false-positive the gate already knows about.
_CAMP_WORD_RE = re.compile(r"\b(?:day\s+camp|summer\s+camp|aileycamp|campers?|camps?)\b", re.I)
_BOOTCAMP_ONLY_RE = re.compile(r"^\W*boot\s*camp\W*$", re.I)


def _has_camp_word(name: str) -> bool:
    n = name or ""
    if _BOOTCAMP_ONLY_RE.match(n):
        return False
    return bool(_CAMP_WORD_RE.search(n))


# --- recruitment / staffing --------------------------------------------------
# "Counselor-in-Training" / "CIT" are real camper programs — exclude them.
_JOB_NAME_RE = re.compile(
    r"\bcounselors?\b(?!\s*[-\s]?in[-\s]?training)"
    r"|\bnow\s+hiring\b|\bwe'?re\s+hiring\b|\bjob\s+opening"
    r"|\bjoin\s+our\s+team\b|\bemployment\s+opportunit"
    r"|\bstaff\s+application\b|\bvolunteer\s+application\b",
    re.I,
)
_JOB_URL_RE = re.compile(
    r"/(?:careers?|jobs?|employment|join-our-team|join-us|work-(?:for|with)-us"
    r"|hiring|staff-application|employment-opportunit)(?:/|$|\?|-)",
    re.I,
)

# --- recurring lessons / open / drop-in --------------------------------------
_LESSON_NAME_RE = re.compile(
    r"\blessons?\b|\bopen\s+(?:gym|play|swim|skate|pool|hours?)\b|\bdrop[-\s]?in\b"
    r"|\bpublic\s+skate\b|\bstick\s*(?:&|and)\s*puck\b|\blap\s+swim\b"
    r"|\bmasters?\s+swim\b|\bpre[-\s]?swim\b|\bswim\s+club\b|\bopen\s+play\b",
    re.I,
)

# --- resource / document / marketing pages -----------------------------------
# Structural indicators only — a real camp is never named "...PDF" / "Newsletter"
# / "FAQ". (No page-specific words: the jewishcamp resource rows are caught by
# the /camp-resources/ path below, which generalizes to any site's resource hub.)
_RESOURCE_NAME_RE = re.compile(
    r"\bnewsletter\b|\bmailing\s+list\b|\bannual\s+report\b|\bpodcast\b"
    r"|\bpress\s+release\b|\bprivacy\s+policy\b|\bpdf\b|\bdownloads?\b"
    r"|\bfaqs?\b|\bblog\s+post\b",
    re.I,
)
# Resource SECTIONS of a site never carry a registrable camp (checked on the
# info page's own path, not the register CTA — gift-card/donate register targets
# are a link-quality problem handled by the extractor, not a drop).
_RESOURCE_URL_RE = re.compile(
    r"/(?:resources?|resource-center|camp-resources|newsroom|press|blog|news"
    r"|podcasts?|downloads?|faqs?)(?:/|$)",
    re.I,
)

# --- year-round childcare / early-learning (non-seasonal) --------------------
# Distinct markers, counted: 2+ on a page is an early-learning/childcare center
# (Springfield JCC ELC finding) even when the page title says "Summer Camp";
# a single weak "year-round" mention only disqualifies a non-camp-named row.
_YEARROUND_MARKERS = (
    re.compile(r"\byear[-\s]?round\b", re.I),
    re.compile(r"\bearly\s+learning\s+center\b", re.I),
    re.compile(r"\bnursery\s+school\b", re.I),
    re.compile(r"\binfant\s+care\b", re.I),
    re.compile(r"\bbefore[-\s]?and[-\s]?after[-\s]?school\b", re.I),
    re.compile(r"\b(?:6|six|8|eight)\s+weeks?\s+(?:to|through|old|[-–])\b", re.I),
    re.compile(r"\bweeks?\s+(?:to|through|[-–])\s+\d+\s+years?\b", re.I),
)


def _yearround_marker_count(blob: str) -> int:
    return sum(1 for rx in _YEARROUND_MARKERS if rx.search(blob))


# Names that are themselves a childcare/early-learning offering (no page text
# needed): "Early Learning Center", "Childcare Program", a bare "Preschool".
_CHILDCARE_NAME_RE = re.compile(
    r"\bearly\s+learning\s+center\b|\blearning\s+center\b|\bchild\s*care\b"
    r"|\bday\s*care\b|\bnursery\b",
    re.I,
)

# --- school-district service / enrollment pages ------------------------------
# Generic special-ed / multilingual / enrollment service categories — no
# program-specific names (e.g. "STRIVE" dropped; "transition services" is the
# generic category that also matches "Transition & STRIVE Services").
_SCHOOL_SERVICE_RE = re.compile(
    r"\benglish\s+(?:as\s+a\s+)?(?:second|supplemental)\s+language\b|\besl\s+program\b"
    r"|\bsupplemental\s+language\b|\bfarm\s+to\s+school\b"
    r"|\btransition\b(?:\s*(?:&|and)\s*\w+)?\s+services?\b"
    r"|\bspecial\s+education\b|\bindividualized\s+education\b"
    r"|\bchange\s+of\s+address\b|\bwelcome\s+services\b|\bproof\s+of\s+residency\b",
    re.I,
)
_SCHOOL_SERVICE_URL_RE = re.compile(
    r"/(?:change-of-address|welcome-services|special-education|esl-program)(?:/|$|-)",
    re.I,
)

# --- higher-ed adult programs (college discovery, Thread 2) -------------------
# College sites are mostly adult/degree content. An adult "Summer Session" can
# carry summer dates and slip the gate's evidence check, so it needs its own
# rule. Requires 2+ distinct higher-ed markers AND no youth signal — a real
# pre-college / youth camp always states its audience (high school, grades,
# ages, rising 9th graders), which protects it.
_HIGHERED_ADULT_RE = re.compile(
    r"\bundergraduate\b|\bgraduate\s+program\b|\bdegree\s+program\b|\bbachelor'?s\b"
    r"|\bmaster'?s\b|\bdoctoral\b|\bph\.?d\b|\badmissions\b|\bstudy\s+abroad\b"
    r"|\bcontinuing\s+education\b|\bprofessional\s+development\b|\bfor\s+credit\b"
    r"|\bcollege\s+credit\b|\bcredit-?bearing\b|\bfinancial\s+aid\b|\bmatriculat"
    r"|\balumni\b|\bfaculty\b|\bsemester\b|\benroll\s+in\s+courses\b",
    re.I,
)
_YOUTH_SIGNAL_RE = re.compile(
    r"\byouth\b|\bkids?\b|\bchildren\b|\bteens?\b|\bhigh\s+school\b|\bmiddle\s+school\b"
    r"|\belementary\b|\bgrades?\s*[k0-9]|\brising\s+(?:[1-9]|k)\b|\bpre-?college\b"
    r"|\bages?\s*\d|\bcampers?\b|\bk-?12\b|\bboys?\b|\bgirls?\b|\bentering\s+grade",
    re.I,
)


def _path(url: str) -> str:
    try:
        return urlparse(url or "").path.lower()
    except ValueError:
        return ""


def noncamp_reason(
    name: str,
    *,
    info_url: str = "",
    register_url: str = "",
    text: str = "",
    dates: str = "",
    is_summer: bool = False,
) -> str | None:
    """Return a short reason this is not a youth summer camp, or None.

    `is_summer` is the caller's own summer-window verdict on `dates`; rules that a
    genuine summer session could otherwise trip (year-round) defer to it.
    """
    name = name or ""
    info_path = _path(info_url)
    blob = f"{name} {text[:4000]}"

    # 1. Recruitment / staffing — never a camp, regardless of youth wording.
    if _JOB_NAME_RE.search(name) or _JOB_URL_RE.search(info_path) or _JOB_URL_RE.search(
        _path(register_url)
    ):
        return "recruitment/job posting"

    # 2. Recurring lessons / open-gym / drop-in — a class series, not a camp.
    if _LESSON_NAME_RE.search(name) and not _has_camp_word(name):
        return "recurring lessons / open-play (not a camp)"

    # 3. Resource / document page (by name OR by the info page's own section).
    if _RESOURCE_NAME_RE.search(name) or _RESOURCE_URL_RE.search(info_path):
        return "resource/document page (not a registrable camp)"

    # 4. School-district service / enrollment page.
    if (
        _SCHOOL_SERVICE_RE.search(blob)
        or _SCHOOL_SERVICE_URL_RE.search(info_path)
        or _SCHOOL_SERVICE_URL_RE.search(_path(register_url))
    ):
        return "school-district service/enrollment page (not a camp)"

    # 5. Year-round childcare / early-learning. A genuine summer session (real
    # summer dates) is always kept. Otherwise: 2+ distinct childcare markers is
    # an early-learning center regardless of a "camp" title; a single marker only
    # disqualifies a row whose name isn't a camp.
    if not is_summer:
        if _CHILDCARE_NAME_RE.search(name) and not _has_camp_word(name):
            return "year-round childcare / early-learning (not seasonal)"
        markers = _yearround_marker_count(blob)
        if markers >= 2 or (markers >= 1 and not _has_camp_word(name)):
            return "year-round childcare / early-learning (not seasonal)"

    # 6. Higher-ed adult program (degree/admissions/credit) with no youth signal
    # — fires even with a summer date (adult "Summer Session"). 2+ distinct
    # markers required so a stray "faculty"/"alumni" can't sink a real camp.
    if not _YOUTH_SIGNAL_RE.search(blob):
        he = {m.group(0).lower() for m in _HIGHERED_ADULT_RE.finditer(blob)}
        if len(he) >= 2:
            return "higher-ed adult program (not a youth camp)"

    return None


# --- field sanitation --------------------------------------------------------
# Zero-padded or implausibly-low bare ages ("age 02", "ages 1") are extraction
# artifacts (a stray "0"/"1"/"2" near "age" on a non-camp page), not real youth
# evidence. Blank them so they neither display as garbage nor count as evidence.
_ZERO_PAD_AGE_RE = re.compile(r"\bages?\s*:?\s*0\d\b", re.I)
_BARE_LOW_AGE_RE = re.compile(r"^\s*ages?\s*:?\s*([0-2])\s*$", re.I)


def sanitize_age(ages: str) -> str:
    """Drop garbage age strings; return a clean value (possibly empty)."""
    a = (ages or "").strip()
    if not a:
        return ""
    if _ZERO_PAD_AGE_RE.search(a):
        return ""
    if _BARE_LOW_AGE_RE.match(a) and "month" not in a.lower() and "week" not in a.lower():
        return ""
    return a


_ADULT_MIN_AGE_RE = re.compile(r"^\s*(?:ages?\s*:?\s*)?(\d{1,2})\s*\+", re.I)
_ADULT_RANGE_RE = re.compile(r"^\s*(?:ages?\s*:?\s*)?(\d{1,2})\s*[-–]\s*\d{1,2}\s*$", re.I)


def adult_min_age(ages: str) -> bool:
    """True when the age field's lower bound is adult (>=18), incl. bare '19+'.

    Months/weeks ("18 months") are never adult.
    """
    a = (ages or "").strip()
    if not a or "month" in a.lower() or "week" in a.lower():
        return False
    m = _ADULT_MIN_AGE_RE.match(a) or _ADULT_RANGE_RE.match(a)
    return bool(m and int(m.group(1)) >= 18)


# --- name accuracy: prefix generic names with the provider ------------------
# A name that is just "Summer Camp" / "Day Camp" / "Older Boys Unit" is
# meaningless to a parent without the operator. Prefix those (and only those)
# with the provider's registry name so "Younger Kids Unit" becomes
# "West Suburban YMCA — Younger Kids Unit". Specific names are left untouched.
_GENERIC_NAME_RE = re.compile(
    r"^(?:the\s+)?"
    r"(?:(?:full|half|all)[-\s]?day\s+|1/2\s*day\s+|outdoor\s+|youth\s+|kids?\s+)?"
    r"(?:summer\s+|day\s+)?"
    r"(?:camps?|programs?|sessions?|units?|summer\s+program|outdoor\s+summer\s+camp)"
    r"\.?$"
    r"|\bunit$",
    re.I,
)


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 2}


def is_generic_name(name: str) -> bool:
    return bool(_GENERIC_NAME_RE.search((name or "").strip()))


def prefixed_name(name: str, provider_name: str) -> str:
    """Prefix a generic camp name with the provider; no-op for specific names or
    when the provider name is already present."""
    name = (name or "").strip()
    provider_name = (provider_name or "").strip()
    if not provider_name or not name or not is_generic_name(name):
        return name
    # Already carries the provider (e.g. "YMCA Summer Camp") -> leave it.
    if _tokens(provider_name) & _tokens(name):
        return name
    return f"{provider_name} — {name}"
