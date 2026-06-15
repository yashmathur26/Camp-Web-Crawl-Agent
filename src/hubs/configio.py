"""HUB ADAPTER ROADMAP H2 — Skyhawks / Configio (register.skyhawks.com) adapter.

Server-rendered GET hub whose register links route into backends we already
adapt (MyRec ProgramID, WebTrac/VermontSystems, ActiveNet/activityreg). The
whole risk here is dedup correctness — a Burlington Skyhawks flag-football camp
can ALSO be a Burlington WebTrac row, so it must collapse to one session_uid
(handled by the orchestrator via src.hub_dedup).

Per product card we extract: title/sport, category subtitle, /pd/{id}/{slug}
detail URL, register affordance, price, status, region, ages, date range,
venue address (+distance), Course #.

register_url splits two ways (H2.2):
  - External Register button present -> register_url = the external URL
    (the true registration endpoint; carlislema.myrec.com / activityreg.com /
    register1.vermontsystems.com ...). info_url stays the /pd page.
  - Internal cart (__doPostBack / no external button) -> register_url = the
    /pd/{id}/{slug} page (the postback isn't a URL; the detail page is the entry).

parent_ready from status text (H2.3): "Available" -> parent_ready; "Full" ->
keep but registrable=False (no open link); "Notify Me" -> hold (not yet open).
"""

from __future__ import annotations

import html as _html
import re
from urllib.parse import urljoin

from src.platforms import CONFIGIO, HUB_SEED, make_session

BASE = "https://register.skyhawks.com"

# Split the result list into per-card chunks at each product-title anchor.
_CARD_SPLIT_RE = re.compile(r'<a[^>]*class="product-title"', re.I)
_PD_HREF_RE = re.compile(r'href="(/pd/\d+/[^"?#]*)', re.I)
_TITLE_TEXT_RE = re.compile(r'class="product-title"[^>]*>(.*?)</a>', re.S | re.I)
_EXTERNAL_RE = re.compile(r'class="[^"]*btn-external-register[^"]*"[^>]*href="([^"]+)"', re.I)
_PRICE_RE = re.compile(r'class="[^"]*price-tag[^"]*"[^>]*>(.*?)</span>', re.S | re.I)
_STATUS_RE = re.compile(r'class="product-status quantity tag">([^<]+)<', re.I)
_REGION_RE = re.compile(r'tag-product-region[^>]*>(.*?)</div>', re.S | re.I)
_CATEGORY_RE = re.compile(r'tag-product-category[^>]*>(.*?)</div>', re.S | re.I)
_AGES_RE = re.compile(r'class="ages-footer">([^<]+)<', re.I)
_START_RE = re.compile(r'title="Start Date:\s*([^"]+)"', re.I)
_END_RE = re.compile(r'title="End Date:\s*([^"]+)"', re.I)
_COURSE_RE = re.compile(r'product-course-number field">\s*<p>([^<]+)</p>', re.I)
_VENUE_TITLE_RE = re.compile(r'class="title bold">([^<]+)<', re.I)
_ADDR1_RE = re.compile(r'class="address1">([^<]+)<', re.I)
_CITY_RE = re.compile(r'class="city">([^<]+)<', re.I)
_STATE_RE = re.compile(r'class="state">([^<]+)<', re.I)
_POSTAL_RE = re.compile(r'class="postal-code">([^<]+)<', re.I)
_DISTANCE_RE = re.compile(r'product-distance[^>]*>(?:[^<]*<[^>]+>)*\s*([\d.]+mi)', re.I)
_POSTBACK_RE = re.compile(r"__doPostBack", re.I)


def _t(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _html.unescape(s or ""))).strip()


def _first(rx: re.Pattern, chunk: str) -> str:
    m = rx.search(chunk)
    return _t(m.group(1)) if m else ""


def parse(html: str) -> list[dict]:
    """Parse a register.skyhawks.com search page into make_session rows.

    Pure function (no network). Cards with no /pd/ detail URL are skipped.
    """
    parts = _CARD_SPLIT_RE.split(html or "")
    rows: list[dict] = []
    seen: set[str] = set()
    # parts[0] is pre-first-card chrome; each subsequent part begins right after
    # a product-title anchor open tag, so re-prepend the marker for full matches.
    for raw in parts[1:]:
        chunk = '<a class="product-title"' + raw
        href_m = _PD_HREF_RE.search(chunk)
        if not href_m:
            continue
        pd_path = _html.unescape(href_m.group(1))
        info_url = BASE + pd_path
        if info_url in seen:
            continue
        seen.add(info_url)

        name = _first(_TITLE_TEXT_RE, chunk)
        status = _first(_STATUS_RE, chunk)
        price = _first(_PRICE_RE, chunk)
        ages = _first(_AGES_RE, chunk)
        category = _first(_CATEGORY_RE, chunk)
        region = _first(_REGION_RE, chunk)
        start = _first(_START_RE, chunk)
        end = _first(_END_RE, chunk)
        course = _first(_COURSE_RE, chunk)
        venue_name = _first(_VENUE_TITLE_RE, chunk)
        addr1 = _first(_ADDR1_RE, chunk)
        city = _first(_CITY_RE, chunk)
        state = _first(_STATE_RE, chunk)
        postal = _first(_POSTAL_RE, chunk)
        distance = _first(_DISTANCE_RE, chunk)

        ext_m = _EXTERNAL_RE.search(chunk)
        external_url = _html.unescape(ext_m.group(1)) if ext_m else ""

        # Status -> registrability (H2.3). The product-status tag is authoritative;
        # the Wait List / Notify Me button labels appear as disabled UI in every
        # card, so they must NOT be scanned chunk-wide.
        low = (status or "").lower()
        is_full = "full" in low
        is_notify = "notify" in low
        available = "available" in low

        registrable = available and not is_full and not is_notify
        # register_url splitting (H2.2)
        if external_url and registrable:
            register_url = urljoin(BASE, external_url)
            reg_node = "external"
        else:
            # Internal cart or not-open: the /pd detail page is the entry point;
            # for Full/Notify we still surface the row but not an open ext link.
            register_url = info_url
            reg_node = "internal" if (_POSTBACK_RE.search(chunk) or not external_url) else "external_held"

        venue = " ".join(p for p in (venue_name, addr1, city, state, postal) if p).strip()
        dates = f"{start} - {end}".strip(" -") if (start or end) else ""
        details = " | ".join(
            p for p in (category, f"Ages {ages}" if ages else "", dates, f"${price}" if price and "$" not in price else price, venue, f"{distance} away" if distance else "")
            if p
        )

        row = make_session(
            name,
            register_url,
            info_url=info_url,
            details_text=details,
            platform=CONFIGIO,
            dates=dates,
            ages=ages,
            price=price,
            source_url=BASE + "/search",
            kind="session",
            name_source="adapter",
        )
        row["venue"] = venue
        row["venue_city"] = city
        row["venue_state"] = state
        row["venue_zip"] = (postal or "")[:5]
        row["start_date"] = start
        row["end_date"] = end
        row["course_no"] = course
        row["region"] = region
        row["category"] = category
        row["distance_mi"] = distance
        row["status_text"] = status
        row["registrable"] = registrable
        row["parent_ready"] = registrable
        row["_register_node"] = reg_node
        row["external_url"] = external_url
        row["_hub"] = "skyhawks"
        row["_hub_class"] = HUB_SEED
        rows.append(row)
    return rows


async def fetch(zip: str, city: str, state: str, radius: int, existing_register_urls: set[str]) -> list[dict]:  # noqa: A002
    """Return make_session rows for one town seed (raw/rendered fetch + parse).

    Walks pagination (?page=N) until a page yields no new cards.
    """
    from config.hubs import hub_search_url
    from src.crawl import fetch_rendered

    base_url = hub_search_url("skyhawks", zip=zip, radius=radius)
    collected: dict[str, dict] = {}
    page = 1
    while page <= 20:
        url = base_url if page == 1 else f"{base_url}&page={page}"
        html = await fetch_rendered(url, wait="networkidle", timeout_s=30)
        rows = parse(html or "")
        new = 0
        for r in rows:
            key = r["info_url"]
            if key not in collected:
                collected[key] = r
                new += 1
        if new == 0:
            break
        page += 1
    out = list(collected.values())
    return [r for r in out if r.get("register_url") not in (existing_register_urls or set())]
