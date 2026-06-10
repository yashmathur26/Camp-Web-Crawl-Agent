"""Community Ed WooCommerce catalog scoping (*communityed.org / .com towns)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

COMMUNITY_ED_HOST_SUFFIXES = ("communityed.org", "communityed.com")
CATALOG_PREFIXES = (
    "lexplorations",
    "childrens-programs",
    "children's-programs",
    "summer",
    "youth",
)
SUMMER_CATEGORY_PATTERNS = re.compile(r"summer|camp|vacation|lexplor", re.I)
SUMMER_PRODUCT_SIGNAL = re.compile(r"summer|camp|vacation|lexplor|youth|kids|children", re.I)
ADULT_CATEGORY_DENY = (
    "cooking",
    "business",
    "esl",
    "exercise-dance",
    "humanities",
    "financial",
    "social-security",
    "grief",
    "mandarin-immersion",
    "adult",
    "senior",
)
WOO_HUB_SLUG_DENY = re.compile(
    r"teens|children-classes|faq|contact|membership|donate|about",
    re.I,
)
AFTERCARE_DENY = re.compile(
    r"after\s*-?\s*care|before\s*-?\s*care|extended\s*day|kidsborough",
    re.I,
)

MAX_COMMUNITY_ED_CATEGORIES = 12
MAX_COMMUNITY_ED_PAGES_PER_CATEGORY = 15


def is_community_ed_host(url: str) -> bool:
    host = urlparse(url).netloc.lower().replace("www.", "")
    return any(host.endswith(s) for s in COMMUNITY_ED_HOST_SUFFIXES)


def resolve_catalog_prefix(url: str) -> str | None:
    """Return path prefix like /lexplorations/ from seed URL."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    root = parts[0].lower()
    if root in {"shop", "class", "product", "wp-content", "info", "programs"}:
        return None
    if root in CATALOG_PREFIXES or any(root.startswith(p) for p in CATALOG_PREFIXES):
        return f"/{parts[0]}/"
    return None


def default_catalog_seed(host: str) -> str:
    return f"https://{host}/lexplorations/find-a-class"


def category_allowed(cat_url: str, prefix: str | None) -> bool:
    path = urlparse(cat_url).path.lower()
    if prefix:
        if path.rstrip("/") in ("/shop", prefix.rstrip("/") + "/shop"):
            return False
        if not path.startswith(prefix.lower()):
            return False
    slug = path.rstrip("/").split("/")[-1]
    if any(d in slug for d in ADULT_CATEGORY_DENY):
        return False
    return bool(SUMMER_CATEGORY_PATTERNS.search(path))


def product_allowed(product_url: str, name: str, prefix: str | None) -> bool:
    path = urlparse(product_url).path.lower()
    if prefix and not path.startswith(prefix.lower()):
        return False
    slug = path.rstrip("/").split("/")[-1]
    if WOO_HUB_SLUG_DENY.search(slug):
        return False
    combined = f"{slug} {name.lower()}"
    if AFTERCARE_DENY.search(combined):
        return False
    return bool(SUMMER_PRODUCT_SIGNAL.search(combined))
