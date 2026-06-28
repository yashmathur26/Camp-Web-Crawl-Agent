"""Phase 2 — register_url resolver (v3 §Phase 2).

Find the REAL signup endpoint for a camp from the outbound links of the pages we
already fetched, with a confidence tier — never by copying info_url. The only way
register_url may equal info_url is a genuine combined page (a known-platform item
page, or an on-page enroll form), which is marked with register_is_info=True so a
real coincidence is distinguishable from the old aliasing bug.

Resolution order (first hit wins, per camp):
  HIGH   — a known-platform outbound link (cross-domain handoff is expected),
           scanned on the camp page first, then its nearest_hub, then other pages.
  MEDIUM — an on-page enroll affordance (cart CTA / enroll form) → the page itself
           is the booking page (register_is_info=True).
  LOW    — a register-intent anchor, CONFIRMED by fetching it and finding an
           affordance on the fetched page (the only place anchor strings are
           trusted, and only as a candidate finder).
  NONE   — nothing found → register_url null. Not a failure; caps verdict at
           info_confirmed; coverage rollup flags it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from engine.fetch.urls import (
    canonical_register_url,
    is_media_url,
    normalize_url,
    register_platform_id,
    to_absolute,
)
from engine.validate.signals import is_platform_host, is_registration_platform_url, verify_registrable

# Register-intent anchors — incl. third-party form hosts (Jotform/Google Forms/
# Formstack/Wufoo/RegFox). Used ONLY as a candidate finder (LOW tier), confirmed
# by fetch+affordance; never the decision itself.
_REG_INTENT_RE = re.compile(
    r"\bregister\b|\benroll\b|\bsign[-\s]?up\b|\bsignup\b|\bapply\b|reg-flow|"
    r"jotform|google\s*form|forms\.gle|docs\.google\.com/forms|formstack|wufoo|"
    r"regfox|regfox\.com|register\.php",
    re.I,
)
# Targets that LOOK like registration but are account/portal/marketing dead-ends.
# Applied as a SAFETY filter on the resolved link only (v3 keeps this).
_BAD_REGISTER_RE = re.compile(
    r"login|sign-?in|/account|my-?account|member-?portal|memberportal|/user/|"
    r"change-of-address|welcome-services|belt-test|gift-?card|mailing-list|"
    r"newsletter|donate|password|logout|destination=|facebook|instagram",
    re.I,
)
_FORM_ACTION_RE = re.compile(r"<form[^>]+action=[\"']([^\"']+)[\"']", re.I)


@dataclass
class RegisterResolution:
    register_url: str = ""          # "" == null / none found
    confidence: str = ""            # high | medium | low | ""
    register_is_info: bool = False

    @property
    def found(self) -> bool:
        return bool(self.register_url)


def _is_platform_link(u: str) -> bool:
    return is_registration_platform_url(u) or is_platform_host(u)


def _platform_candidates(links: list[dict]) -> list[str]:
    """Known-platform outbound links from one page's link list, bad targets out."""
    out: list[str] = []
    seen: set[str] = set()
    for l in links or []:
        raw = l.get("url", "")
        if not raw or is_media_url(raw):
            continue
        u = normalize_url(raw)
        if not u or u in seen:
            continue
        if _BAD_REGISTER_RE.search(raw):
            continue
        if _is_platform_link(raw):
            seen.add(u)
            out.append(raw)
    return out


def _score(url: str, *, on_own_page: bool, on_hub: bool) -> int:
    score = 20 if on_own_page else (10 if on_hub else 0)
    if register_platform_id(canonical_register_url(url)):
        score += 5            # an item-id link beats a platform root
    return score


def _has_affordance(url: str, html_or_text: str, *, context: str = "") -> bool:
    sig = verify_registrable(url, html_or_text or "", context=context)
    if sig.has_cart_cta or sig.auto_verdict == "parent_ready":
        return True
    # Phase 3 feature: a real enroll/booking form on the page is also an affordance.
    from engine.extract.features import _ENROLL_FORM_RE
    return bool(_ENROLL_FORM_RE.search(html_or_text or ""))


def resolve_register(
    camp_url: str,
    *,
    own_links: list[dict],
    own_html: str,
    nearest_hub: str = "",
    hub_links: list[dict] | None = None,
    other_page_links: list[tuple[str, list[dict]]] | None = None,
    context: str = "",
    fetch=None,
) -> RegisterResolution:
    """Resolve a register link for one camp. `fetch` is an optional callable
    `fetch(url) -> (text, links, html)` used only to confirm a LOW-tier candidate;
    omit it (offline/no-budget) and LOW simply yields NONE — fail safe."""

    # --- Tier HIGH: known-platform outbound link ---------------------------
    candidates: list[tuple[str, int]] = []
    for u in _platform_candidates(own_links):
        candidates.append((u, _score(u, on_own_page=True, on_hub=False)))
    for u in _platform_candidates(hub_links or []):
        candidates.append((u, _score(u, on_own_page=False, on_hub=True)))
    for _purl, plinks in (other_page_links or []):
        for u in _platform_candidates(plinks):
            candidates.append((u, _score(u, on_own_page=False, on_hub=False)))
    if candidates:
        best = max(candidates, key=lambda c: c[1])[0]
        is_info = normalize_url(best) == normalize_url(camp_url)
        return RegisterResolution(register_url=best, confidence="high",
                                  register_is_info=is_info)

    # --- Tier MEDIUM: on-page enroll affordance ----------------------------
    if _has_affordance(camp_url, own_html, context=context):
        action = ""
        m = _FORM_ACTION_RE.search(own_html or "")
        if m:
            action = to_absolute(camp_url, m.group(1))
        if action and normalize_url(action) != normalize_url(camp_url) \
                and not _BAD_REGISTER_RE.search(action):
            return RegisterResolution(register_url=action, confidence="medium")
        return RegisterResolution(register_url=camp_url, confidence="medium",
                                  register_is_info=True)

    # --- Tier LOW: register-intent anchor, confirmed by fetch --------------
    if fetch is not None:
        for l in own_links or []:
            raw = l.get("url", "")
            blob = f"{raw} {l.get('text', '')}"
            if not raw or is_media_url(raw) or _BAD_REGISTER_RE.search(raw):
                continue
            if not _REG_INTENT_RE.search(blob):
                continue
            try:
                ftext, _flinks, fhtml = fetch(raw)
            except Exception:  # noqa: BLE001 — a dead candidate is simply NONE
                continue
            if _has_affordance(raw, fhtml or ftext, context=context):
                return RegisterResolution(register_url=raw, confidence="low")
            break  # only the top intent candidate is worth a fetch

    # --- Tier NONE ---------------------------------------------------------
    return RegisterResolution()


# Confidence → verdict ceiling (v3 §Phase 2). The gate consumes this.
def verdict_ceiling(confidence: str, *, evidence_clean: bool) -> str:
    if confidence == "high":
        return "parent_ready"
    if confidence == "medium":
        return "parent_ready" if evidence_clean else "needs_review"
    if confidence == "low":
        return "needs_review"
    return "info_confirmed"   # null / none
