"""Phase 3 — feature-based page-role classification (v3 §Phase 3).

Decide a page's ROLE from what it DOES, not from its URL slug, so it generalizes
across sites. Promotes the `EnrollmentSignals` / `verify_registrable` markers from
verdict-upgrade-only to a first-class classifier:

  registration — enroll form / cart CTA / price-near-date (a booking page)
  info         — descriptive prose + program fields, no enroll affordance
  peripheral   — neither + about/alumni/news/logistics structure (not this camp)

When the features are decisive that IS the answer — no LLM (Phase 4 only sees the
residue this can't resolve). URL/host matching is reserved for platform detection
and hard denies; it never decides role here.

Feeds: Phase 2's MEDIUM tier (on-page affordance) and Phase 6L's parent_url rung-1
role guard (don't hand a parent a peripheral page).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from engine.fetch.urls import is_media_url, normalize_url
from engine.validate.signals import (
    CART_CTA_RE,
    PRICE_RE,
    is_platform_host,
    is_registration_platform_url,
)

_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ENROLL_FORM_RE = re.compile(
    r"<form[^>]*>(?:(?!</form>)[\s\S]){0,4000}?"
    r"(?:register|enroll|sign\s*up|add\s*to\s*cart|checkout|book\s*now)",
    re.I,
)
_DATE_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,2}"
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\bweek\s+of\b|summer\s+20\d{2}",
    re.I,
)
# Structures that mark a NON-camp page (about/alumni/news/logistics/policies).
_PERIPHERAL_RE = re.compile(
    r"\b(?:about\s+us|our\s+(?:mission|story|history|staff|team|board)|alumni|"
    r"class\s+of\s+\d{4}|press\s+release|in\s+the\s+news|newsletter|"
    r"privacy\s+policy|terms\s+of\s+(?:use|service)|directions?|parking|"
    r"refund\s+policy|cancellation\s+policy|frequently\s+asked)\b",
    re.I,
)

_STOP = {"the", "a", "an", "of", "and", "for", "at", "in", "to", "with", "camp"}


def _name_in_h1(name: str, html: str) -> bool:
    m = _H1_RE.search(html or "")
    if not m:
        return False
    h1 = _TAG_RE.sub(" ", m.group(1)).lower()
    toks = [t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in _STOP]
    if not toks:
        return False
    return sum(1 for t in toks if t in h1) >= max(1, len(toks) - 1)


def _links_to_known_platform(links: list[dict] | None) -> bool:
    for l in links or []:
        u = l.get("url", "")
        if not u or is_media_url(u):
            continue
        if is_registration_platform_url(u) or is_platform_host(u):
            return True
    return False


@dataclass
class PageFeatures:
    has_enroll_form: bool = False
    has_cart_cta: bool = False
    has_price: bool = False
    has_date: bool = False
    links_to_known_platform: bool = False
    is_hub: bool = False
    name_in_h1: bool = False
    text_len: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def page_features(
    url: str, html: str, text: str, *, name: str = "",
    links: list[dict] | None = None, is_hub: bool = False,
) -> PageFeatures:
    body = html or text or ""
    return PageFeatures(
        has_enroll_form=bool(_ENROLL_FORM_RE.search(html or "")),
        has_cart_cta=bool(CART_CTA_RE.search(body)),
        has_price=bool(PRICE_RE.search(body)),
        has_date=bool(_DATE_RE.search(text or body)),
        links_to_known_platform=_links_to_known_platform(links),
        is_hub=is_hub,
        name_in_h1=_name_in_h1(name, html),
        text_len=len((text or "").strip()),
    )


def classify_role(f: PageFeatures) -> str:
    """registration | info | peripheral from decisive page features."""
    # A booking affordance is decisive for registration.
    if f.has_enroll_form or f.has_cart_cta or (f.has_price and f.has_date):
        return "registration"
    # Descriptive page with program fields and no affordance → info.
    if f.text_len >= 400 and (f.has_date or f.has_price or f.name_in_h1):
        return "info"
    # Otherwise peripheral (about/alumni/news/logistics/thin).
    return "peripheral"


def role_of_page(
    url: str, html: str, text: str, *, name: str = "",
    links: list[dict] | None = None, is_hub: bool = False,
    peripheral_markers: int = 2,
) -> tuple[str, PageFeatures]:
    """Convenience: features + role, with a peripheral-structure override so an
    about/alumni/news page with incidental dates still classifies peripheral."""
    f = page_features(url, html, text, name=name, links=links, is_hub=is_hub)
    role = classify_role(f)
    if role == "info" and not (f.has_enroll_form or f.has_cart_cta):
        hits = len(set(m.group(0).lower() for m in _PERIPHERAL_RE.finditer((text or html or "")[:6000])))
        if hits >= 1 and not f.name_in_h1:
            role = "peripheral"
    return role, f
