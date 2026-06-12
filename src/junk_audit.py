"""Machine-checkable definition of a "junk" camp-session row.

roadmap2.md §1 documents the failure corpus (chrome names, off-topic register
URLs, evidence-free rows). This module turns those into a single, scriptable
predicate so every later phase can *measure* improvement instead of arguing
about it:

- Phase 0 freezes the current bad run and audits it with `audit_row`.
- Phase 1 (name integrity) reuses `is_chrome_name` to refuse chrome names.
- Phase 5 (validation gate) reuses `audit_row` to quarantine bad rows before
  they reach the deliverable CSV.

Keep this dependency-light (no crawl4ai / playwright) so it can run in tests
and in the write path without pulling the browser stack.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import tldextract

from src.registration import is_registration_platform_url

# Exact button / nav / cookie-banner chrome that must never be a camp name.
# Normalized (lowercased, collapsed whitespace, trailing punctuation stripped)
# before comparison.
CHROME_LABELS: frozenset[str] = frozenset(
    {
        "back to top",
        "skip to main content",
        "skip to content",
        "skip to cookie notice",
        "skip to footer",
        "manage cookies",
        "cookie notice",
        "accept cookies",
        "see details",
        "details",
        "more info",
        "more information",
        "learn more",
        "read more",
        "view all",
        "view more",
        "show more",
        "register",
        "register here",
        "register now",
        "register online",
        "enroll",
        "enroll now",
        "sign up",
        "sign up now",
        "signup",
        "join waitlist",
        "join the waitlist",
        "waitlist",
        "add to cart",
        "checkout",
        "click here",
        "home",
        "menu",
        "close",
        "search",
        "next",
        "previous",
        "back",
        "continue",
        "submit",
        "login",
        "log in",
        "sign in",
        "my account",
        "contact",
        "contact us",
    }
)

# Chrome that varies by site but follows a fixed shape (e.g. "skip to <X>").
_CHROME_PATTERNS = re.compile(
    r"^(?:skip to\b.*|back to\b.*|jump to\b.*|go to\b.*|"
    r"toggle\b.*|open\b.*menu|close\b.*menu)$",
    re.I,
)

_FILE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|pdf|docx?|xlsx?|css|js)$", re.I)
_BARE_ID_RE = re.compile(r"^[#\-\s]*\d[\d\s\-#]*$")
# A "name" that is really a squashed domain token, e.g. "Themunroecenterforthearts".
_SQUASHED_DOMAIN_RE = re.compile(r"^[a-z]{18,}$")


def _normalize_label(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().strip(".:|–-").lower()).strip()


def is_chrome_name(name: str) -> bool:
    """True if *name* is button/menu/cookie chrome, not a real program name."""
    norm = _normalize_label(name)
    if not norm:
        return False
    if norm in CHROME_LABELS:
        return True
    return bool(_CHROME_PATTERNS.match(norm))


def is_unusable_name(name: str) -> bool:
    """Chrome, a bare ID/number, a filename, or a squashed-domain token."""
    raw = (name or "").strip()
    if not raw:
        return True
    if is_chrome_name(raw):
        return True
    if _FILE_EXT_RE.search(raw):
        return True
    if _BARE_ID_RE.match(raw):
        return True
    if _SQUASHED_DOMAIN_RE.match(raw.replace(" ", "").lower()) and " " not in raw:
        return True
    return False


# External form/registration hosts that are legitimate camp register targets
# even though they live off the provider's domain (roadmap2 Phase 4 allow-list).
# Complements `is_registration_platform_url` (municipal/portal systems).
REGISTER_HOST_ALLOWLIST: tuple[str, ...] = (
    "jotform.com",
    "docs.google.com",
    "forms.gle",
    "forms.office.com",
    "regfox.com",
    "wufoo.com",
    "formstack.com",
    "typeform.com",
    "eventbrite.com",
    "signupgenius.com",
    "campscui.active.com",
)


def _is_allowed_register_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(sub in host for sub in REGISTER_HOST_ALLOWLIST)


def _registered_domain(url: str) -> str:
    if not url:
        return ""
    ext = tldextract.extract(urlparse(url).netloc or url)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return (urlparse(url).netloc or "").lower()


def is_offhost_register(register_url: str, *reference_urls: str) -> bool:
    """True if the register URL leaves the provider's domain *and* is not a
    recognized registration platform (Jotform/WebTrac/etc.)."""
    if not register_url:
        return False
    if is_registration_platform_url(register_url) or _is_allowed_register_host(register_url):
        return False
    reg_dom = _registered_domain(register_url)
    if not reg_dom:
        return False
    refs = {_registered_domain(u) for u in reference_urls if u}
    refs.discard("")
    if not refs:
        return False
    return reg_dom not in refs


def has_evidence(session: dict) -> bool:
    """At least one of age / date / price is present."""
    return any((session.get(k) or "").strip() for k in ("ages", "dates", "price"))


def audit_row(session: dict) -> list[str]:
    """Return the machine-checkable junk reasons for a session row (empty = clean)."""
    reasons: list[str] = []
    name = session.get("name", "")
    if is_chrome_name(name):
        reasons.append("chrome_name")
    elif is_unusable_name(name):
        reasons.append("unusable_name")

    reg = (session.get("register_url") or "").strip()
    if not reg:
        reasons.append("no_register_url")
    elif is_offhost_register(
        reg, session.get("info_url", ""), session.get("source_url", "")
    ):
        reasons.append("offhost_register")

    if not has_evidence(session):
        reasons.append("no_evidence")

    return reasons


def is_junk(session: dict) -> bool:
    return bool(audit_row(session))


# URL sections that are never a youth camp (anti-drift backstop at write time).
_OFF_TOPIC_URL_RE = re.compile(
    r"/(?:research|clinical|psychiatry|imaging|radiology|oncology|pubmed|"
    r"faculty|publications?|careers?|investor|press|newsroom|patient)\b",
    re.I,
)


def validate_session(session: dict) -> tuple[bool, list[str]]:
    """roadmap2 Phase 5 gate: (ok, reasons). A session may be published only when
    it has a real name, a registrable URL on an allowed host, at least one of
    {age,date,price}, and is on-topic. Reasons are the machine-checkable tags.

    This is the backstop — it mostly passes because Phases 1-4 cleaned the data;
    anything still bad is quarantined rather than published."""
    reasons = audit_row(session)
    # Task 1.2: provider-level fallback rows (granularity="program") are honest
    # "this provider runs a summer program" pointers — they carry no per-session
    # age/date/price by design, so no_evidence does not apply to them.
    if (session.get("granularity") or "") == "program":
        reasons = [r for r in reasons if r != "no_evidence"]
    for key in ("register_url", "info_url", "source_url"):
        u = session.get(key) or ""
        if u and _OFF_TOPIC_URL_RE.search(urlparse(u).path):
            reasons.append("off_topic")
            break
    return (not reasons, reasons)


def is_fabrication_blocked(session: dict) -> bool:
    """True when the pipeline refused to fabricate from a thin/login page
    (Phase 4 marked it) — counted separately in the run summary."""
    return (session.get("extract_status") or "") in ("needs_js", "login_wall", "empty")
