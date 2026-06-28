"""Enrollment signals — PORTED from src/enrollment_signals.py (R2: owned here).

Pure URL+HTML check: does this page show a parent-usable register affordance
(cart CTA / price / platform enroll markers)? Used by the gate's optional
register-verification step — may upgrade a verdict to `parent_ready`, never
blocks an `info_confirmed` row (plan §8.4).

Port notes: the old module pulled should_auto_drop/HUB_PATH_RE from two other
src modules; their URL-junk roles are covered here by a single JUNK_URL_RE.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qs, urlparse

CART_CTA_RE = re.compile(
    r"add[- ]to[- ]cart|addtocart|enroll\s+now|register\s+now|"
    r"sign\s+up\s+now|proceed\s+to\s+(checkout|payment)|"
    r"checkout|place\s+order|buy\s+now|register\s+online",
    re.I,
)
PRICE_RE = re.compile(
    r"\$\s?\d{2,4}(?:\.\d{2})?|woocommerce-Price-amount|program\s+fee|"
    r"tuition|cost:\s*\$|price:\s*\$",
    re.I,
)
YOUTH_CAMP_RE = re.compile(
    r"summer\s+camp|day\s+camp|ages?\s+\d|grades?\s+[k0-9]|"
    r"week\s+of|june|july|august|youth|kids?|children|clinic|lexplorations",
    re.I,
)
ADULT_BLOCKER_RE = re.compile(
    r"adult\s+education|continuing\s+education|18\+|ages?\s+18|"
    r"senior\s+center|after[- ]school|year[- ]round\s+childcare|"
    r"men'?s\s+league|women'?s\s+league|workforce\s+development|"
    r"for\s+adults",
    re.I,
)
BROCHURE_ONLY_RE = re.compile(
    r"contact\s+us\s+to\s+register|call\s+to\s+register|registration\s+opens|"
    r"download\s+brochure|coming\s+soon",
    re.I,
)
LOGIN_WALL_RE = re.compile(
    r"sign\s+in\s+to\s+register|log\s+in\s+to\s+register|members?\s+only|"
    r"create\s+an\s+account\s+to\s+enroll",
    re.I,
)
CATALOG_ROW_RE = re.compile(
    r"program_details\.aspx\?ProgramID=|iteminfo\.aspx\?FMID=|"
    r"/class/[^/\s\"']+|add-to-cart",
    re.I,
)
WEBTRAC_CART_RE = re.compile(r"addtocart|iteminfo|module=ar|webtrac", re.I)
WOO_CART_RE = re.compile(r"woocommerce|add-to-cart|single_add_to_cart", re.I)
MYREC_ENROLL_RE = re.compile(r"register|enroll|add\s+to\s+cart|program_details", re.I)

# Junk URL sections that never carry a register affordance (consolidates the
# old should_auto_drop + HUB_PATH_RE imports).
JUNK_URL_RE = re.compile(
    r"/(?:about|contact|faq|privacy|terms|careers?|employment|news|blog|"
    r"donate|membership|gallery|photos)(?:/|$)|\.pdf($|\?)",
    re.I,
)


# Known registration-platform hosts (plan core reframe: a host IS a reliable
# fingerprint — match these, classify everything else from content). Kept here as
# the ONE place the gate/extractors ask "is this a known platform?". Mirrors the
# proposer's VENDOR_SIGNATURES plus the handoff platforms (capturepoint, pinwheel)
# the register-url resolver follows.
PLATFORM_HOST_RE = re.compile(
    r"myvscloud\.com|webtrac|myrec\.com|campscui\.active\.com|activecommunities\.com|"
    r"hisawyer\.com|campbrain(?:registration)?\.com|enrollsy\.com|daxko\.com|"
    r"recdesk\.com|civicrec|communitypass\.net|ultracamp\.com|capturepoint\.com|"
    r"pinwheel\.us|communityed\.(?:org|com)",
    re.I,
)


def is_platform_host(url: str) -> bool:
    """True when the URL's host is a known registration platform (a fingerprint,
    not a guess). Reserved for host matching; page role comes from content."""
    return bool(PLATFORM_HOST_RE.search(urlparse(url or "").netloc.lower()))


@dataclass
class EnrollmentSignals:
    has_cart_cta: bool = False
    has_price: bool = False
    has_catalog_menu: bool = False
    platform_confidence: float = 0.0
    youth_camp_keywords: bool = False
    blockers: list[str] = field(default_factory=list)
    auto_verdict: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _count_catalog_rows(html: str) -> int:
    return len(CATALOG_ROW_RE.findall(html))


def _platform_type(url: str) -> str:
    low = url.lower()
    host = urlparse(url).netloc.lower()
    if "myvscloud" in low or "webtrac" in low:
        return "webtrac"
    if "myrec.com" in host or "program_details" in low:
        return "myrec"
    if "communityed" in host:
        return "community_ed"
    if "woocommerce" in low or "/class/" in low or "/product/" in low:
        return "woocommerce"
    return "generic"


def is_registration_platform_url(url: str) -> bool:
    """Public: does this URL point at a known platform's item/registration page
    (WebTrac iteminfo, MyRec program_details, CommunityEd /class/, /product/)?"""
    return _is_platform_session_url(url)


def _is_platform_session_url(url: str) -> bool:
    low = url.lower()
    if "iteminfo" in low and "fmid=" in low.replace(" ", ""):
        return True
    if "program_details.aspx" in low:
        qs = parse_qs(urlparse(url).query)
        if qs.get("ProgramID") or qs.get("programid"):
            return True
    path = urlparse(url).path
    if re.search(r"/class/[^/]+/?$", path, re.I):
        host = urlparse(url).netloc.lower()
        if host.endswith("communityed.org") or host.endswith("communityed.com"):
            return True
    if re.search(r"/product/[^/]+/?$", path, re.I):
        return True
    return False


def verify_registrable(url: str, html: str, *, context: str = "") -> EnrollmentSignals:
    """Pure URL+HTML registrability check. `context` (e.g. program name) only
    informs the youth/adult keyword tests, never the cart checks."""
    text = html or ""
    blob = f"{context} {text[:8000]}".strip()

    sig = EnrollmentSignals(
        has_cart_cta=bool(CART_CTA_RE.search(text)),
        has_price=bool(PRICE_RE.search(text)),
        has_catalog_menu=_count_catalog_rows(text) >= 3,
        youth_camp_keywords=bool(YOUTH_CAMP_RE.search(blob)),
    )

    if JUNK_URL_RE.search(url or ""):
        sig.blockers.append("junk_url")
        sig.auto_verdict = "wrong_audience"
        return sig

    if ADULT_BLOCKER_RE.search(blob) and not YOUTH_CAMP_RE.search(context):
        sig.blockers.append("adult_ed")
        sig.auto_verdict = "wrong_audience"
        return sig

    if LOGIN_WALL_RE.search(text) and not sig.has_cart_cta:
        sig.blockers.append("login_wall")

    plat = _platform_type(url or "")
    is_session = _is_platform_session_url(url or "")

    if plat == "webtrac":
        sig.platform_confidence = 0.9 if WEBTRAC_CART_RE.search(text) else 0.5
        if is_session and (sig.has_cart_cta or WEBTRAC_CART_RE.search(text)):
            sig.auto_verdict = "parent_ready"
            return sig

    if plat == "myrec":
        sig.platform_confidence = 0.85 if MYREC_ENROLL_RE.search(text) else 0.5
        if is_session and (sig.has_cart_cta or MYREC_ENROLL_RE.search(text)):
            sig.auto_verdict = "parent_ready"
            return sig

    if plat in ("woocommerce", "community_ed"):
        sig.platform_confidence = 0.85 if WOO_CART_RE.search(text) else 0.4
        if is_session and WOO_CART_RE.search(text) and sig.has_price:
            sig.auto_verdict = "parent_ready"
            return sig

    if sig.has_catalog_menu and sig.has_cart_cta and sig.youth_camp_keywords:
        sig.platform_confidence = max(sig.platform_confidence, 0.7)
        sig.auto_verdict = "parent_ready"
        return sig

    if not text.strip():
        sig.blockers.append("empty_page")
        return sig

    if sig.youth_camp_keywords and sig.has_price and sig.has_cart_cta:
        sig.auto_verdict = "parent_ready"
        return sig

    if sig.youth_camp_keywords and not sig.has_cart_cta and BROCHURE_ONLY_RE.search(text):
        sig.blockers.append("brochure_only")

    return sig
