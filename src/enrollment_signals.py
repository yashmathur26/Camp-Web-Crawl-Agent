"""Deterministic HTML signals for parent enrollment verification."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from urllib.parse import parse_qs, urlparse

from src.camp_validator import should_auto_drop
from src.session_quality import HUB_PATH_RE
from src.urls import normalize_url

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
    r"men'?s\s+league|women'?s\s+league|workforce\s+development",
    re.I,
)
BROCHURE_ONLY_RE = re.compile(
    r"contact\s+us\s+to\s+register|call\s+to\s+register|registration\s+opens|"
    r"learn\s+more|download\s+brochure|coming\s+soon",
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
    if "recdesk" in host:
        return "recdesk"
    if "civicrec" in host:
        return "civicrec"
    return "generic"


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


def verify_registrable(url: str, html: str) -> EnrollmentSignals:
    """Pure URL+HTML check for parent registrability (no session/phase context)."""
    return _compute_enrollment_signals(url, html, extra_context="")


def extract_enrollment_signals(
    url: str,
    html: str,
    *,
    session_name: str = "",
) -> EnrollmentSignals:
    """Phase P wrapper; session name informs youth/adult keyword checks."""
    return _compute_enrollment_signals(url, html, extra_context=session_name)


def _compute_enrollment_signals(
    url: str,
    html: str,
    *,
    extra_context: str = "",
) -> EnrollmentSignals:
    text = html or ""
    low_url = (url or "").lower()
    blob = f"{extra_context} {text[:8000]}".strip()

    sig = EnrollmentSignals(
        has_cart_cta=bool(CART_CTA_RE.search(text)),
        has_price=bool(PRICE_RE.search(text)),
        has_catalog_menu=_count_catalog_rows(text) >= 3,
        youth_camp_keywords=bool(YOUTH_CAMP_RE.search(blob)),
    )

    if should_auto_drop(url)[0] or HUB_PATH_RE.search(url):
        sig.blockers.append("junk_url")
        sig.auto_verdict = "wrong_audience"
        return sig

    if ADULT_BLOCKER_RE.search(blob) and not YOUTH_CAMP_RE.search(extra_context):
        sig.blockers.append("adult_ed")
        sig.auto_verdict = "wrong_audience"
        return sig

    if LOGIN_WALL_RE.search(text) and not sig.has_cart_cta:
        sig.blockers.append("login_wall")

    plat = _platform_type(url)
    is_session = _is_platform_session_url(url)

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
        if "lexplorations" in low_url and WOO_CART_RE.search(text):
            sig.auto_verdict = "parent_ready"
            return sig

    if sig.has_catalog_menu and sig.has_cart_cta:
        sig.platform_confidence = max(sig.platform_confidence, 0.7)
        if sig.youth_camp_keywords:
            sig.auto_verdict = "parent_ready"
            return sig

    if not text.strip():
        sig.blockers.append("empty_page")
        return sig

    if sig.youth_camp_keywords and not sig.has_cart_cta and BROCHURE_ONLY_RE.search(text):
        sig.blockers.append("brochure_only")
        sig.auto_verdict = "brochure_only"
        return sig

    if sig.youth_camp_keywords and sig.has_price and sig.has_cart_cta:
        sig.auto_verdict = "parent_ready"
        return sig

    if sig.youth_camp_keywords and not sig.has_cart_cta and not sig.has_catalog_menu:
        sig.blockers.append("brochure_only")
        sig.auto_verdict = "brochure_only"

    return sig


def verdict_from_signals(signals: EnrollmentSignals, html: str) -> str:
    """Map signals + fetched HTML to a parent_verdict string."""
    if not (html or "").strip():
        return "fetch_failed"
    if signals.auto_verdict:
        return signals.auto_verdict
    if signals.blockers:
        return signals.blockers[0] if signals.blockers[0] in (
            "brochure_only",
            "wrong_audience",
            "login_wall",
        ) else "unverified"
    return "unverified"


def attach_inline_verification(
    session: dict,
    url: str,
    html: str,
    *,
    session_name: str = "",
) -> dict:
    """Set parent_verdict on a session when the register page HTML is in hand."""
    name = session_name or session.get("name", "")
    signals = extract_enrollment_signals(url, html, session_name=name)
    verdict = verdict_from_signals(signals, html)
    reason = signals.auto_verdict or (
        signals.blockers[0] if signals.blockers else "rules inconclusive"
    )
    return {
        **session,
        "parent_verdict": verdict,
        "parent_can_register": verdict == "parent_ready",
        "enrollment_signals": json.dumps(signals.to_dict()),
        "parent_verify_reason": reason,
    }


def can_verify_inline(session: dict, fetched_url: str) -> bool:
    """True when fetched_url is the register page for this session."""
    reg = normalize_url(session.get("register_url") or "")
    fetched = normalize_url(fetched_url)
    if reg and fetched and reg == fetched:
        return True
    return session.get("kind") == "portal" and bool(fetched)
