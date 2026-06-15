"""HUB ADAPTER ROADMAP H3 — iD Tech (idtech.com) adapter (SPA funnel).

Three-hop funnel:
  1. location-search?s={city},+{state},+USA -> nearby campus cards + slugs.
  2. per campus -> reg-flow page (…/locations/{state}/{campus}#/reg-flow/
     avail-charts-lock?lid={lid}&rgnad=true). The AngularJS availability grid is
     materialized in the rendered DOM (rows=courses, cols=week ranges, cells=status).
  3. grid -> sessions: emit ONLY Open-with-price cells; skip empty cells and
     "Try online" (emitting those fabricates sessions for weeks that don't run).

Three-node mapping:
  register_url = the campus reg-flow page  (shared across all sessions at the
                 campus — acceptable per H3.2)
  info_url     = per-course info URL (distinct per course)
  details_text = "Ages 7-9 • Beg-Adv • 1 Week • from $1,129"
  platform     = IDTECH ; kind = "session"
"""

from __future__ import annotations

import html as _html
import re

from src.platforms import HUB_SEED, IDTECH, make_session

BASE = "https://www.idtech.com"

# --- Hop 1: location search -------------------------------------------------
_LOC_CARD_RE = re.compile(r'<div class="row location">(.*?)(?=<div class="row location">|<footer|</main)', re.S)
_LOC_LINK_RE = re.compile(r'href="(/locations/[a-z0-9\-]+-summer-camps/[a-z0-9\-]+)"', re.I)
_LOC_NAME_RE = re.compile(r'class="location-name">([^<]+)<', re.I)
_LOC_ADDR_RE = re.compile(r'class="location-address">([^<]+)<', re.I)
_LOC_DIST_RE = re.compile(r'class="location-distance">([^<]+)<', re.I)
_LOC_STATUS_RE = re.compile(r'location-status--(\w+)', re.I)
_LOC_INFO_RE = re.compile(r'class="info-line">([^<]+)<', re.I)


def _t(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(s or ""))).strip()


def parse_locations(html: str) -> list[dict]:
    """Hop 1: campus cards from a location-search page (pure, no network)."""
    out: list[dict] = []
    seen: set[str] = set()
    for m in _LOC_CARD_RE.finditer(html or ""):
        block = m.group(1)
        lm = _LOC_LINK_RE.search(block)
        if not lm:
            continue
        path = lm.group(1)
        if path in seen:
            continue
        seen.add(path)
        info = [_t(x) for x in _LOC_INFO_RE.findall(block)]
        out.append({
            "name": _t((_LOC_NAME_RE.search(block) or [None, ""])[1]) if _LOC_NAME_RE.search(block) else "",
            "url": BASE + path,
            "slug": path.rstrip("/").split("/")[-1],
            "state_slug": path.split("/")[2],
            "venue": _t((_LOC_ADDR_RE.search(block) or [None, ""])[1]) if _LOC_ADDR_RE.search(block) else "",
            "distance": _t((_LOC_DIST_RE.search(block) or [None, ""])[1]) if _LOC_DIST_RE.search(block) else "",
            "status": (_LOC_STATUS_RE.search(block) or [None, ""])[1] if _LOC_STATUS_RE.search(block) else "",
            "info_lines": info,
        })
    return out


# --- Hops 2/3: reg-flow availability grid -----------------------------------
_COURSE_ROW_RE = re.compile(r'class="[^"]*course-row[^"]*"', re.I)
_COURSE_NAME_RE = re.compile(r'class="[^"]*course-name[^"]*"[^>]*>([^<]+)<', re.I)
_AGES_RE = re.compile(r"Ages:\s*([\d\-+]+)", re.I)
_LEVEL_RE = re.compile(r">(Beg[\w\-]*|Int[\w\-]*|Adv[\w\-]*|Beg-Adv)<", re.I)
_PRICE_RE = re.compile(r"from\s*<span[^>]*>\s*(\$[\d,]+(?:\s*USD)?)", re.I)
_PRODUCT_ID_RE = re.compile(r'data-id-product-id="(\d+)"', re.I)
_LOCATION_ID_RE = re.compile(r'data-id-location-id="(\d+)"', re.I)
_LID_RE = re.compile(r"lid(?:%5B%5D|\[\])?=(\d+)", re.I)
# An Open session: a date range bound + a text-open / >Open< status nearby.
_DATE_RANGE_RE = re.compile(
    r">([A-Z][a-z]{2}\s+\d{1,2}\s*-\s*(?:[A-Z][a-z]{2}\s+)?\d{1,2})<"
)


def reg_flow_url(campus_url: str, lid: str) -> str:
    base = campus_url.split("#", 1)[0]
    return f"{base}#/reg-flow/avail-charts-lock?lid={lid}&rgnad=true"


def parse_reg_flow(html: str, *, campus_url: str = "", campus_venue: str = "") -> list[dict]:
    """Hops 2/3: Open+priced sessions from a campus reg-flow grid (pure).

    Rows are courses; we emit one session per Open cell that carries a date range.
    Mobile+desktop render the same cell twice, so sessions are deduped by
    (product_id, date_range). Empty / NA / "Try online" cells are never emitted.
    """
    lid_m = _LID_RE.search(html or "") or _LOCATION_ID_RE.search(html or "")
    lid = lid_m.group(1) if lid_m else ""
    register_url = reg_flow_url(campus_url, lid) if campus_url else ""

    # Split into per-course blocks at each course-row marker.
    spans = [m.start() for m in _COURSE_ROW_RE.finditer(html or "")]
    spans.append(len(html or ""))
    rows: list[dict] = []
    seen: set[tuple] = set()
    for i in range(len(spans) - 1):
        block = html[spans[i]:spans[i + 1]]
        name_m = _COURSE_NAME_RE.search(block)
        if not name_m:
            continue
        name = _t(name_m.group(1))
        ages = (_AGES_RE.search(block) or [None, ""])[1] if _AGES_RE.search(block) else ""
        level_m = _LEVEL_RE.search(block)
        level = _t(level_m.group(1)) if level_m else ""
        price_m = _PRICE_RE.search(block)
        price = _t(price_m.group(1)) if price_m else ""
        pid_m = _PRODUCT_ID_RE.search(block)
        product_id = pid_m.group(1) if pid_m else ""

        # Find Open cells: a date range whose surrounding cell text says Open.
        for dm in _DATE_RANGE_RE.finditer(block):
            window = block[max(0, dm.start() - 400): dm.end() + 400]
            if ">Open<" not in window and "text-open" not in window:
                continue
            if "try online" in window.lower():
                continue
            if not price:
                continue  # emit only Open-WITH-price cells
            date_range = _t(dm.group(1))
            key = (product_id or name, date_range)
            if key in seen:
                continue
            seen.add(key)
            details = " • ".join(p for p in (f"Ages {ages}" if ages else "", level, "1 Week", f"from {price}") if p)
            row = make_session(
                name,
                register_url or campus_url,
                details_text=details,
                platform=IDTECH,
                dates=date_range,
                ages=ages,
                price=price,
                source_url=campus_url,
                kind="session",
                name_source="adapter",
            )
            # Distinct per-course info_url (set post-construction: make_session's
            # normalize_url strips a #fragment, which would collapse all to the
            # campus URL). The register_url stays the shared reg-flow page.
            campus_base = (campus_url or "").split("#", 1)[0]
            # Preserve the hash-route reg-flow register URL (normalize_url in
            # make_session strips #fragments) — the roadmap's canonical register
            # endpoint for an iD Tech session is the campus reg-flow page.
            if register_url:
                row["register_url"] = register_url
            row["info_url"] = (
                f"{campus_base}#course-{product_id}" if (campus_base and product_id) else (campus_url or "")
            )
            row["venue"] = campus_venue
            row["start_date"] = date_range
            row["product_id"] = product_id
            row["lid"] = lid
            row["parent_ready"] = True
            row["registrable"] = True
            row["status_text"] = "Open"
            row["_hub"] = "idtech"
            row["_hub_class"] = HUB_SEED
            rows.append(row)
    return rows


async def fetch(zip: str, city: str, state: str, radius: int, existing_register_urls: set[str]) -> list[dict]:  # noqa: A002
    """Three-hop live fetch for one city seed. Campuses enumerated once per city."""
    from config.hubs import hub_search_url
    from src.crawl import fetch_rendered

    search_url = hub_search_url("idtech", city=city, state=state, page=1)
    loc_html = await fetch_rendered(search_url, wait="networkidle", timeout_s=40)
    campuses = parse_locations(loc_html or "")
    out: list[dict] = []
    seen_campus: set[str] = set()
    for c in campuses:
        # only MA campuses (state_slug) — venue geo gate runs later too
        if "massachusetts" not in c["state_slug"]:
            continue
        if c["url"] in seen_campus:
            continue
        seen_campus.add(c["url"])
        grid_html = await fetch_rendered(c["url"], wait="networkidle", timeout_s=45)
        out.extend(parse_reg_flow(grid_html or "", campus_url=c["url"], campus_venue=c["venue"]))
    return [r for r in out if r.get("register_url") not in (existing_register_urls or set())]
