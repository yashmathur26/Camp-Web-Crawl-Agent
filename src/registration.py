"""Detect municipal recreation registration systems (WebTrac, MyRec, etc.)."""

import re
from urllib.parse import parse_qs, urlparse

# Nav/footer links that never lead to a youth summer camp registration.
# Used to prune the crawl queue so we don't vacuum entire rec-center sites.
JUNK_PATH_RE = re.compile(
    r"(/about|/staff|/staff-directory|/contact|/privacy|/terms|/refund|"
    r"/faq|/faqs|/membership|/donate|/give|/volunteer|/employment|/jobs|"
    r"/careers|/news|/blog|/events|/calendar|/birthday|/rental|/facility|"
    r"/aquatics|/skating|/gym|/fitness|/adult|/senior|/login|/signin|"
    r"/account|/cart|/directions|/hours|/board|/history|/mission|"
    r"/sponsors|/partners|/press|/media|/photo|/gallery|/after-school|"
    r"/afterschool|/preschool|/childcare|/sitemap|/search-results|"
    r"/program/teens|/program/children-classes|/government/|/discover/contact|"
    r"wp-content/uploads|\.pdf($|\?))",
    re.IGNORECASE,
)

from config.platforms_registry import registration_host_substrings

# Hosts/paths that usually host camp registration catalogs.
# Registry signatures plus legacy aliases not tied to a B.5 adapter.
REGISTRATION_PLATFORM_HOST_SUBSTRINGS: tuple[str, ...] = tuple(
    dict.fromkeys(
        registration_host_substrings()
        + (
            "activenet",
            "activenetwork",
            "arux.app",
        )
    )
)

_REGISTRATION_PATH_RE = re.compile(
    r"webtrac|program_details\.aspx|/register|/registration|"
    r"type=camp|module=ar|/courses?/|/enroll",
    re.IGNORECASE,
)


def is_registration_platform_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    host = urlparse(url).netloc.lower()
    if any(sub in host for sub in REGISTRATION_PLATFORM_HOST_SUBSTRINGS):
        return True
    if any(sub in lower for sub in REGISTRATION_PLATFORM_HOST_SUBSTRINGS):
        return True
    if _REGISTRATION_PATH_RE.search(lower):
        return True
    qs = parse_qs(urlparse(url).query)
    type_vals = [v.lower() for v in qs.get("type", [])]
    if any("camp" in v for v in type_vals):
        return True
    return False


# WebTrac "noise" actions/views that are NOT a camp catalog (cart, item churn).
_CATALOG_NOISE_RE = re.compile(
    r"action=updateselection|/iteminfo\.|addtocart|"
    r"option=(dates|enrollmentcounts)|arfmidlist=|interfaceparameter=",
    re.IGNORECASE,
)


def is_camp_catalog_url(url: str) -> bool:
    """The terminal target: a registration catalog filtered/landing on CAMPS.

    e.g. WebTrac search.html?module=AR&type=CAMP or category=...Camp, or a MyRec
    program_details page for a camp. This is what we keep — NOT every link inside
    a registration system (pool/dance/cart/waitlist/per-session item pages)."""
    if not url:
        return False
    lower = url.lower()
    if _CATALOG_NOISE_RE.search(lower):
        return False
    qs = {k.lower(): [v.lower() for v in vals] for k, vals in parse_qs(urlparse(url).query).items()}
    if any("camp" in v for v in qs.get("type", [])):
        return True
    if any("camp" in v for v in qs.get("category", [])):
        return True
    if "program_details.aspx" in lower and "camp" in lower:
        return True
    return False


def registration_url_priority(url: str) -> int:
    """Higher = better final camp link (catalog/search beats generic landing)."""
    if not is_registration_platform_url(url):
        return 0
    lower = url.lower()
    score = 10
    if is_camp_catalog_url(url):
        score += 30
    if "webtrac" in lower and "type=camp" in lower.replace(" ", ""):
        score += 20
    if "program_details" in lower:
        score += 15
    if "module=ar" in lower:
        score += 5
    return score


def crawl_link_score(url: str, text: str = "") -> int:
    """Traversal priority for a link found while crawling a rec-center site.

    Higher = visit sooner. Negative/zero-ish for junk. Used by the focused
    priority-queue crawl in crawl.py.
        100+  registration catalog (the goal — visit first)
         60   any registration platform link
         40   camp/summer/program path or text
         10   other on-site link worth a look
         -1   junk nav (about/staff/privacy/...) — caller should skip
    """
    if not url:
        return -1
    lower = url.lower()
    combined = f"{lower} {(text or '').lower()}"
    if is_camp_catalog_url(url):
        return 120
    if is_registration_platform_url(url):
        return 60
    if JUNK_PATH_RE.search(urlparse(url).path):
        return -1
    if re.search(r"summer-?camp|day-?camp|lexplor", combined):
        return 50
    if re.search(r"\bcamp\b|/camps?(/|$)|summer|register|registration|program|enroll|activit", combined):
        return 40
    return 10
