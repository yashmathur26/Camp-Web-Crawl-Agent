"""Phase 6L — link bundle: homepage_url, the parent_url ladder, the two output
surfaces (parent CSV + Firecrawl manifest), and merge-back (v3 §4, §6L).

The deliverable a human reads carries exactly ONE link per camp — `parent_url`,
always populated, the page we're most confident about. The uncertain link
(`register_url`) lives only in the internal Firecrawl manifest. One set of gated
rows, two views; content from the content pages, link from the confident page.
"""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

from engine.extract.generic import is_camp_catalog_url
from engine.fetch.urls import canonical_register_url, normalize_url
from engine.model import Program
from engine.validate.gate import _registrable_domain, is_hub_slug
from engine.validate.signals import (
    PLATFORM_HOST_RE,
    is_registration_platform_url,
)


def _host_is_platform(host: str) -> bool:
    """is_platform_host expects a URL; this takes a bare host string."""
    return bool(PLATFORM_HOST_RE.search((host or "").lower()))

PARENT_COLUMNS = ["camp_id", "display_name", "parent_url", "dates", "ages", "price", "town"]
MANIFEST_COLUMNS = ["camp_id", "info_url", "register_url", "nearest_hub", "register_confidence"]


def _is_hub_url(url: str) -> bool:
    return is_hub_slug(url) or is_camp_catalog_url(url)


def platform_catalog_root(info_url: str) -> str:
    """The org's catalog/search root on a platform — NOT the bare vendor root
    (invariant §2.2.3): myvscloud → that org's WebTrac search.html."""
    p = urlparse(info_url)
    if not p.netloc:
        return ""
    if "myvscloud" in p.netloc or "/webtrac/" in p.path.lower():
        return f"{p.scheme}://{p.netloc}/webtrac/web/search.html"
    return f"{p.scheme}://{p.netloc}/"


def derive_homepage(provider, info_url: str) -> str:
    """homepage_url (§6L.1): the provider's OWN site when known; for a
    platform-hosted provider, its registry site or the platform catalog root —
    never the bare vendor root."""
    host = (getattr(provider, "host", "") or "").lower()
    if host and not _host_is_platform(host):
        return f"https://{_registrable_domain(host)}/"
    seed = getattr(provider, "seed_url", "") or ""
    seed_host = urlparse(seed).netloc.lower()
    if seed_host and not _host_is_platform(seed_host):
        return f"https://{_registrable_domain(seed_host)}/"
    if info_url:
        return platform_catalog_root(info_url)
    return f"https://{host}/" if host else ""


def derive_parent_url(sess, homepage_url: str) -> str:
    """parent_url ladder (§6L.2). Rung 1: the camp's own confident page (info or
    registration role, not a hub). Rung 2: the nearest hub that CONTAINS it.
    Rung 3: the homepage floor. Confirmed rows already passed the gate's
    name-on-page invariant, so rung-1's name guard is met."""
    info = sess.info_url
    role_ok = (
        sess.page_role in ("info", "registration")
        or is_registration_platform_url(info)
    )
    if info and role_ok and not _is_hub_url(info):
        return info                       # rung 1
    if sess.nearest_hub:
        return sess.nearest_hub           # rung 2
    return homepage_url                   # rung 3


def parent_rung(sess, homepage_url: str) -> int:
    """Which rung produced parent_url (for the Phase 6 distribution)."""
    pu = sess.parent_url or derive_parent_url(sess, homepage_url)
    if pu == sess.info_url and sess.info_url:
        return 1
    if pu == sess.nearest_hub and sess.nearest_hub:
        return 2
    return 3


def annotate_link_bundle(provider, programs: list[Program]) -> None:
    """Set homepage_url + parent_url on every confirmed session of a provider."""
    for prog in programs:
        for sess in prog.sessions:
            sess.homepage_url = derive_homepage(provider, sess.info_url)
            sess.parent_url = derive_parent_url(sess, sess.homepage_url)


def firecrawl_content_urls(programs: list[Program], homepage_url: str = "") -> list[str]:
    """Deduped per-provider content set (§6L.3): info pages ∪ real signups ∪
    nearest hubs (∪ homepage if otherwise thin), so a hub shared by 30 camps is
    crawled ONCE. Identity via normalize_url / canonical_register_url."""
    seen: set[str] = set()
    out: list[str] = []

    def _add(url: str) -> None:
        if not url:
            return
        key = canonical_register_url(url) or normalize_url(url)
        if key and key not in seen:
            seen.add(key)
            out.append(url)

    for prog in programs:
        for s in prog.sessions:
            _add(s.info_url)
            if s.register_url:
                _add(s.register_url)
            if s.nearest_hub:
                _add(s.nearest_hub)
    if len(out) <= 1 and homepage_url:
        _add(homepage_url)
    return out


def write_link_views(out_dir: Path, programs: list[Program], town: str) -> dict[str, int]:
    """Write the two deliverable surfaces (§4): the parent-facing CSV (one link
    per camp = parent_url) and the internal Firecrawl manifest (keyed by camp_id,
    carries the messy content links). Returns row counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    parent_rows, manifest_rows = [], []
    for prog in programs:
        for s in prog.sessions:
            parent_rows.append({
                "camp_id": s.session_id,
                "display_name": s.display_name or s.name,
                "parent_url": s.parent_url or s.homepage_url,
                "dates": s.dates, "ages": s.ages, "price": s.price, "town": town,
            })
            manifest_rows.append({
                "camp_id": s.session_id, "info_url": s.info_url,
                "register_url": s.register_url, "nearest_hub": s.nearest_hub,
                "register_confidence": s.register_confidence,
            })
    for fname, cols, rows in (
        ("parent_camps.csv", PARENT_COLUMNS, parent_rows),
        ("firecrawl_manifest.csv", MANIFEST_COLUMNS, manifest_rows),
    ):
        with open(out_dir / fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    return {"parent_camps.csv": len(parent_rows),
            "firecrawl_manifest.csv": len(manifest_rows)}


def merge_back(parent_rows: list[dict], firecrawl_by_camp: dict[str, dict]) -> list[dict]:
    """Join Firecrawl's extracted content (keyed by camp_id) onto the parent rows:
    enrich descriptive columns (description/dates/ages/price) ONLY — `parent_url`
    never changes (§4.3, content from content pages, link from the confident page)."""
    enrich_cols = ("description", "dates", "ages", "price")
    out = []
    for row in parent_rows:
        merged = dict(row)
        extracted = firecrawl_by_camp.get(row.get("camp_id", ""), {})
        for col in enrich_cols:
            val = (extracted.get(col) or "").strip() if extracted else ""
            if val:
                merged[col] = val            # parent_url intentionally untouched
        out.append(merged)
    return out
