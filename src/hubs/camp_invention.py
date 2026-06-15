"""HUB ADAPTER ROADMAP H1 — Camp Invention (invent.org) adapter.

Cleanest hub: a GET-templated program search whose `parent_ready` status is
enforced by the URL itself (field_program_status_value_1[]=pre-registration|
registration). The result list is AJAX-injected, but every program teaser is
*also* embedded in the page's `drupal-settings-json` Leaflet feature list
(map markers), so a single rendered fetch yields the full, parseable catalog
with venue address, dates, and the per-program register/detail link.

Three-node mapping per program:
  name         = data-program / teaser title (school + camp type)
  register_url = https://www.invent.org{href}  (the /program-search/.../{id} page)
  info_url     = same detail page
  details_text = dates + venue
  geo_*        = parsed from the teaser address (venue, never the seed ZIP)
  platform     = CAMP_INVENTION ; kind = "session"
"""

from __future__ import annotations

import html as _html
import json
import re

from src.platforms import CAMP_INVENTION, HUB_SEED, make_session

BASE = "https://www.invent.org"

_SETTINGS_JSON_RE = re.compile(
    r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>',
    re.S,
)
_HREF_RE = re.compile(r'href="(/program-search/[^"]+)"')
_TITLE_RE = re.compile(r'class="program-teaser__title"[^>]*>(.*?)</h3>', re.S)
_DATA_PROGRAM_RE = re.compile(r'data-program="([^"]*)"')
_DATE_RE = re.compile(r'class="program-teaser__date"[^>]*>(.*?)</p>', re.S)
_ADDRESS_RE = re.compile(r'class="program-teaser__address"[^>]*>(.*?)</div>', re.S)
_REGISTER_BTN_RE = re.compile(r'class="[^"]*program-teaser__register[^"]*"[^>]*>(.*?)</div>', re.S)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(s or ""))).strip()


def _iter_features(node, out: list) -> None:
    if isinstance(node, dict):
        feats = node.get("features")
        if isinstance(feats, list):
            out.extend(feats)
        for v in node.values():
            _iter_features(v, out)
    elif isinstance(node, list):
        for v in node:
            _iter_features(v, out)


def parse(html: str) -> list[dict]:
    """Parse a rendered invent.org program-search page into make_session rows.

    Pure function (no network) — the H1 characterization test runs it against the
    saved fixture and asserts the exact card count.
    """
    m = _SETTINGS_JSON_RE.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    features: list = []
    _iter_features(data, features)

    rows: list[dict] = []
    seen: set[str] = set()
    for feat in features:
        teaser = ((feat or {}).get("popup") or {}).get("value") or ""
        if "program-teaser" not in teaser:
            continue
        href_m = _HREF_RE.search(teaser)
        if not href_m:
            continue
        href = _html.unescape(href_m.group(1))
        register_url = BASE + href
        if register_url in seen:
            continue
        seen.add(register_url)

        name = _text((_DATA_PROGRAM_RE.search(teaser) or [None, ""])[1]) if _DATA_PROGRAM_RE.search(teaser) else ""
        if not name:
            tm = _TITLE_RE.search(teaser)
            name = _text(tm.group(1)) if tm else ""
        dm = _DATE_RE.search(teaser)
        dates = _text(dm.group(1)) if dm else ""
        am = _ADDRESS_RE.search(teaser)
        venue = _text(am.group(1)) if am else ""
        bm = _REGISTER_BTN_RE.search(teaser)
        reg_text = _text(bm.group(1)) if bm else ""

        lat = feat.get("lat")
        lon = feat.get("lon")
        details = " | ".join(p for p in (dates, venue) if p)
        row = make_session(
            name,
            register_url,
            info_url=register_url,
            details_text=details,
            platform=CAMP_INVENTION,
            dates=dates,
            source_url=BASE + "/program-search",
            kind="session",
            name_source="adapter",
        )
        row["venue"] = venue
        row["start_date"] = dates
        row["_hub"] = "camp_invention"
        row["_hub_class"] = HUB_SEED
        row["lat"] = lat
        row["lon"] = lon
        # URL pre-filters to pre-registration|registration; presumptively open.
        row["parent_ready"] = True
        row["registrable"] = True
        row["status_text"] = reg_text
        rows.append(row)
    return rows


async def fetch(zip: str, city: str, state: str, radius: int, existing_register_urls: set[str]) -> list[dict]:  # noqa: A002
    """Return make_session rows for one town seed (rendered fetch + parse)."""
    from config.hubs import hub_search_url
    from src.crawl import fetch_rendered

    url = hub_search_url("camp_invention", zip=zip, radius=radius)
    html = await fetch_rendered(url, wait="networkidle", timeout_s=35)
    rows = parse(html or "")
    return [r for r in rows if r.get("register_url") not in (existing_register_urls or set())]
