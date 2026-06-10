import re
from urllib.parse import urlparse

import tldextract

from config.sources import (
    AGGREGATOR_DENY_DOMAINS,
    GUIDE_DOMAINS,
    REGISTRATION_SIGNAL_SUBSTRINGS,
)
from src.camp_hosts import is_camp_host_seed_url, is_rec_center_host
from src.registration import is_camp_catalog_url, is_registration_platform_url

_KEEP_PATTERNS = re.compile(
    r"camp|program|class|clinic|session|academy|workshop|lessons|summer",
    re.IGNORECASE,
)

_DROP_PATH_PATTERNS = re.compile(
    r"(/login|/signin|/cart|/privacy|/terms|/about|/contact|/after-school|/afterschool)(/|$|\?)",
    re.IGNORECASE,
)

_COMMUNITY_ED_DROP_PATH = re.compile(
    r"(/class-category/|/category/|/tag/|/author/|add-to-cart=|/wait-listed|/adult-programs)",
    re.IGNORECASE,
)

_SUMMER_CAMP_SIGNAL = re.compile(
    r"camp|summer|lexplor|children|youth|kids|vacation",
    re.IGNORECASE,
)

DENY_DOMAINS = {
    "mail.google.com",
    "printfriendly.com",
    "facebook.com",
    "fb.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "wikipedia.org",
    "reddit.com",
    "pinterest.com",
    "patch.com",
    "cnn.com",
    "nytimes.com",
    "washingtonpost.com",
    "bostonglobe.com",
    "boston.com",
    "nbcnews.com",
    "abcnews.go.com",
    "cbsnews.com",
    "foxnews.com",
    "usatoday.com",
    "reuters.com",
    "apnews.com",
} | set(AGGREGATOR_DENY_DOMAINS)


def _registered_domain(url: str) -> str:
    parsed = urlparse(url)
    ext = tldextract.extract(parsed.netloc)
    if not ext.domain or not ext.suffix:
        return parsed.netloc.lower()
    return f"{ext.domain}.{ext.suffix}".lower()


def _is_community_ed_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("communityed.org") or host.endswith("communityed.com")


def _is_denylisted(url: str) -> bool:
    domain = _registered_domain(url)
    if domain in DENY_DOMAINS:
        return True
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith(".gov") and any(
        seg in parsed.path.lower() for seg in ("/press", "/news", "/media")
    ):
        return True
    return False


def _passes_community_ed_rules(url: str, text: str) -> bool:
    """Tighten community-ed catalogs: drop nav hubs; require camp signals on class pages."""
    if not _is_community_ed_host(url):
        return True
    lower_url = url.lower()
    if _COMMUNITY_ED_DROP_PATH.search(lower_url):
        return False
    path = urlparse(url).path.lower()
    # /class-category/ contains "/class/" as substring — check category hubs first.
    if "/class-category/" in path or path.rstrip("/").endswith("/class-category"):
        return False
    if re.search(r"/class/[^/]+", path):
        combined = f"{lower_url} {(text or '').lower()}"
        return bool(_SUMMER_CAMP_SIGNAL.search(combined))
    return True


def is_likely_camp_link(url: str, text: str) -> bool:
    if not url:
        return False
    # On a registration platform, keep ONLY the camp catalog/search page —
    # never the pool/dance/cart/waitlist/per-session churn links.
    if is_registration_platform_url(url):
        return is_camp_catalog_url(url)
    lower_url = url.lower()
    if lower_url.startswith(("mailto:", "tel:", "#")):
        return False
    if is_camp_host_seed_url(url):
        return True
    if _is_denylisted(url):
        return False
    combined = f"{url} {text or ''}"
    if is_rec_center_host(url) and _KEEP_PATTERNS.search(combined):
        if _DROP_PATH_PATTERNS.search(lower_url) and "camp" not in combined.lower():
            return False
        if not _passes_community_ed_rules(url, text):
            return False
        return True
    if _DROP_PATH_PATTERNS.search(lower_url):
        return False
    if not _passes_community_ed_rules(url, text):
        return False
    if _KEEP_PATTERNS.search(combined):
        return True
    return False


_ASSET_EXT_RE = re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|css|js|ico)(\?|$)", re.IGNORECASE)


def is_external_camp_lead(guide_url: str, link_url: str, text: str) -> bool:
    """A guide's outbound link worth keeping: a real camp/registration site,
    on a DIFFERENT domain than the guide, not another aggregator/guide/social,
    and showing a registration signal."""
    if not link_url:
        return False
    lower = link_url.lower()
    if lower.startswith(("mailto:", "tel:", "#")):
        return False
    if _ASSET_EXT_RE.search(lower):
        return False
    guide_dom = _registered_domain(guide_url)
    link_dom = _registered_domain(link_url)
    if link_dom == guide_dom:
        return False  # internal link — not an outbound recommendation
    if link_dom in AGGREGATOR_DENY_DOMAINS:
        return False  # social / news / junk
    if link_dom in GUIDE_DOMAINS:
        return False  # guide → guide hop, drop
    if is_registration_platform_url(link_url):
        return is_camp_catalog_url(link_url)
    combined = f"{lower} {(text or '').lower()}"
    return any(sig in combined for sig in REGISTRATION_SIGNAL_SUBSTRINGS)
