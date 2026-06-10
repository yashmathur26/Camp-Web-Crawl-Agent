"""Drop harvest slop: admin pages, national indexes, out-of-state, LexCE category hubs."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from config.settings import STATE
from src.geo_filter import is_out_of_state_url

# Trade associations / national finders — not registrable local camps.
_NATIONAL_INDEX_HOSTS: frozenset[str] = frozenset({
    "acacamps.org",
    "bgca.org",
    "jcca.org",
    "ymca.org",
    "find.acacamps.org",
    "connect.acacamps.org",
})

_ADMIN_PATH = re.compile(
    r"(/membership|/donate|/conference|/financial-aid|/partners|/latest-news|"
    r"/events-education|/events\?|parent-handbook|/cafeteria|/vacation-programs|"
    r"/swim-lessons|/kids-classes|/after-school|after-school-program|"
    r"/drop-program|/wait-listed|/how-to-register|/contact-us|/my-account)(/|$|\?)",
    re.I,
)

_PDF_PATH = re.compile(r"\.pdf($|\?)", re.I)

# LexCE / WooCommerce noise (category hubs, cart, account — not camp sessions).
_CATALOG_HUB_PATH = re.compile(
    r"(/class-category/|/product-category/|/product-tag/|/shop/|add-to-cart=|"
    r"/wait-listed-classes|/find-a-class/?$|/lexplorations/?$|"
    r"/cart/?$|/track-your-orders|/frequently-asked-questions|"
    r"/how-to-register|/my-account|/contact-us|/wait-listed)",
    re.I,
)

_DENY_HOSTS = frozenset({
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
})

_BAD_LINK_TEXT = re.compile(
    r"^(skip to main content|open|read more|learn more|click here)$",
    re.I,
)


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def drop_reason(url: str, text: str = "") -> str | None:
    """Return a short reason if this link is slop, else None."""
    if not url:
        return "empty url"

    oos, reason = is_out_of_state_url(url, title=text, state=STATE)
    if oos:
        return reason

    host = _host(url)
    if host in _DENY_HOSTS:
        return "social media"

    if host in _NATIONAL_INDEX_HOSTS or host.endswith(".acacamps.org"):
        return "national camp index (not a local provider)"

    if host == "lexingtonymca.com":
        return "Lexington, Kentucky YMCA (wrong town)"

    lower = url.lower()
    if _CATALOG_HUB_PATH.search(lower):
        return "catalog category hub (not a camp session)"

    if _ADMIN_PATH.search(lower):
        return "admin / ancillary page"

    if _PDF_PATH.search(lower):
        return "PDF handout (not registration page)"

    if _BAD_LINK_TEXT.match((text or "").strip()):
        return "junk link text"

    # Community-ed class pages must mention summer/youth — not adult fall classes.
    if host.endswith("communityed.org") and "/class/" in lower and "/class-category/" not in lower:
        combined = f"{lower} {(text or '').lower()}"
        if not re.search(r"camp|summer|lexplor|youth|kids|children|vacation", combined, re.I):
            return "community-ed page without youth summer signal"

    return None


def is_quality_camp_link(url: str, text: str = "") -> bool:
    return drop_reason(url, text) is None
