"""Per-platform camp enumeration adapters.

Lexington (and most MA towns) spread their camps across ~12 registration
platforms. Each exposes its catalog differently, so a single crawler can't
enumerate them all. This module detects the platform behind a provider URL and
dispatches to the right adapter, returning a uniform list of `Session` dicts.

Adapter tiers:
  - STRUCTURED (clean URL patterns -> exact per-session links):
      WebTrac/myvscloud, WooCommerce, MyRec
  - PORTAL (JS/queue registration; we surface the registration entry point(s)
      plus any per-program links we can see): Sawyer, CampBrain, ArbiterSports,
      ACTIVE/CommunityPass/Daxko
  - LLM FALLBACK (marketing site builders w/ camps described in prose):
      Squarespace, Wix, Weebly, generic WordPress, custom

Every adapter returns list[Session]; an empty list means "nothing enumerable
here" and the caller can fall back. A Session always carries enough for the
downstream Firecrawl detail-extraction pass: a name and a register_url.
"""

from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import parse_qs, urljoin, urlparse

from src.junk_audit import is_unusable_name
from src.urls import normalize_url

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Session shape
# --------------------------------------------------------------------------- #
# info_url == register_url is only valid for single-page platforms (WebTrac
# iteminfo, MyRec program_details). The navigator (Phase 3) MUST set info_url
# to the detail page and register_url to the distinct checkout — never default
# them equal.
def make_session(
    name: str,
    register_url: str,
    *,
    info_url: str = "",
    details_text: str = "",
    platform: str = "",
    dates: str = "",
    ages: str = "",
    price: str = "",
    source_url: str = "",
    kind: str = "session",
    name_source: str = "",
) -> dict:
    """Uniform record every adapter returns.

    kind: "session" = a specific registrable camp; "portal" = a registration
    entry point we couldn't break into per-session links (Firecrawl/JS needed).
    info_url: per-camp detail page (distinct from register_url when known).
    name_source: provenance of the name (e.g. "adapter", "link_text", "title",
    "llm", "slug") — recorded so the validation gate and audits can reason about
    where a name came from.

    Phase 1 (name integrity): a chrome/button/menu/filename string is never
    published as a name. Such a row keeps flowing with name="" and
    name_status="needs_name" (raw text preserved in raw_name for debugging), so
    a later phase can recover a real name or quarantine the row — but the chrome
    string itself never reaches the deliverable CSV.
    """
    from config.settings import SETTINGS

    raw_name = (name or "").strip()
    if SETTINGS.get("b5_name_integrity", True) and is_unusable_name(raw_name):
        clean_name = ""
        name_status = "needs_name"
    else:
        clean_name = raw_name
        name_status = "ok"

    return {
        "name": clean_name,
        "register_url": normalize_url(register_url) or register_url,
        "info_url": normalize_url(info_url) if info_url else "",
        "details_text": (details_text or "").strip(),
        "platform": platform,
        "dates": dates.strip(),
        "ages": ages.strip(),
        "price": price.strip(),
        "source_url": source_url,
        "kind": kind,
        "name_source": name_source,
        "name_status": name_status,
        "raw_name": raw_name if name_status == "needs_name" else "",
    }


# --------------------------------------------------------------------------- #
# Platform detection
# --------------------------------------------------------------------------- #
WEBTRAC = "webtrac"
WOOCOMMERCE = "woocommerce"
COMMUNITY_ED = "community_ed"
MYREC = "myrec"
SAWYER = "sawyer"
CAMPBRAIN = "campbrain"
ARBITER = "arbitersports"
ACTIVE = "active"
COMMUNITYPASS = "communitypass"
DAXKO = "daxko"
VERACROSS = "veracross"
ULTRACAMP = "ultracamp"
RECDESK = "recdesk"
CIVICREC = "civicrec"
PERFECTMIND = "perfectmind"
JACKRABBIT = "jackrabbit"
CAMPDOC = "campdoc"
CAMPMINDER = "campminder"
YMCA = "ymca"
SQUARESPACE = "squarespace"
WIX = "wix"
WEEBLY = "weebly"
WORDPRESS = "wordpress"
CATALOG_GRID = "catalog_grid"
CUSTOM = "custom"

# Multi-course catalog grids (iD Tech, STEM hosts, camp marketplaces): many same-host
# detail URLs under /courses|programs|camps|classes|activities|.../{slug}.
_CATALOG_GRID_SEGMENTS = (
    "courses",
    "programs",
    "camps",
    "classes",
    "activities",
    "offerings",
    "workshops",
    "sessions",
)
_CATALOG_GRID_SEG_ALT = "|".join(_CATALOG_GRID_SEGMENTS)
_CATALOG_GRID_ITEM_RE = re.compile(
    rf"^/(?P<seg>{_CATALOG_GRID_SEG_ALT})/(?P<slug>[a-z0-9][a-z0-9\-]{{2,}})/?$",
    re.I,
)
_CATALOG_GRID_SLUG_DENY = re.compile(
    r"elementary|middle-school|high-school|competition|mental-health|wellness|"
    r"nutrition|opioid|self-management|first-aid|volunteer|training$",
    re.I,
)
_CATALOG_GRID_SLUG_REQUIRE = re.compile(
    r"camp|summer|week|session|clinic|academy|vacation|youth|kids",
    re.I,
)
_CATALOG_GRID_LISTING_RE = re.compile(
    rf"/(?P<seg>{_CATALOG_GRID_SEG_ALT})/?$",
    re.I,
)
_CATALOG_GRID_SKIP_SLUGS = frozenset({
    "index",
    "search",
    "category",
    "categories",
    "all",
    "featured",
    "archive",
    "archives",
    "page",
    "tag",
    "tags",
})
_CATALOG_GRID_MIN_ITEMS = 8
_CATALOG_GRID_MIN_ITEMS_WITH_COUNTER = 5

from config.community_ed import (
    MAX_COMMUNITY_ED_CATEGORIES,
    MAX_COMMUNITY_ED_PAGES_PER_CATEGORY,
    category_allowed,
    is_community_ed_host,
    product_allowed,
    resolve_catalog_prefix,
)
from config.platforms_registry import builder_host_signatures, host_signatures

# Host substrings that identify an external registration platform.
_HOST_SIGNATURES: list[tuple[str, tuple[str, ...]]] = host_signatures()

# Site-builder signatures detectable in cleaned page text / link hosts.
_BUILDER_HOST_SIGNATURES: list[tuple[str, tuple[str, ...]]] = builder_host_signatures()


def _hosts_of(links: list[dict]) -> set[str]:
    hosts = set()
    for link in links:
        net = urlparse(link.get("url", "")).netloc.lower()
        if net.startswith("www."):
            net = net[4:]
        if net:
            hosts.add(net)
    return hosts


_YMCA_HOST_RE = re.compile(r"ymca\.(org|net|com)|ymcaboston|ymcaof", re.I)
_JCC_HOST_RE = re.compile(r"jcc[a-z0-9\-]*\.org", re.I)
_EMBED_PLATFORM_RE = re.compile(
    r"myvscloud\.com|webtrac|daxko|operations\.daxko|veracross\.com",
    re.I,
)
_PROGRAM_CATALOG_HOSTS = frozenset({"vikingcamps.com"})
_PROGRAM_SLUG_RE = re.compile(r"^/program/[^/]+/?$", re.I)
_WOO_CATEGORY_RE = re.compile(
    r"/(class-category|product-category|shop|find-a-class)(/|$|\?)",
    re.IGNORECASE,
)
_WOO_SIGNATURE_RE = re.compile(
    r"woocommerce|add-to-cart|wp-content/plugins/woocommerce",
    re.IGNORECASE,
)


def _woo_category_links(url: str, links: list[dict]) -> list[dict]:
    """Same-host links to WooCommerce category/catalog listing pages."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    out = []
    for l in links:
        u = l.get("url", "")
        h = urlparse(u).netloc.lower().replace("www.", "")
        if h == host and _WOO_CATEGORY_RE.search(urlparse(u).path + "?" + urlparse(u).query):
            out.append(l)
    return out


def _catalog_grid_host(url: str) -> str:
    return urlparse(url).netloc.lower().replace("www.", "")


def _parse_catalog_grid_item(url: str) -> re.Match[str] | None:
    return _CATALOG_GRID_ITEM_RE.match(urlparse(url).path)


def _is_catalog_grid_item(seed_url: str, link: dict) -> bool:
    u = normalize_url(link.get("url", ""))
    if not u:
        return False
    if _catalog_grid_host(u) != _catalog_grid_host(seed_url):
        return False
    m = _parse_catalog_grid_item(u)
    if not m:
        return False
    return m.group("slug").lower() not in _CATALOG_GRID_SKIP_SLUGS


def _catalog_grid_segments_from_links(seed_url: str, links: list[dict]) -> list[str]:
    """Rank catalog path segments by how many detail items appear on this host."""
    counts: dict[str, int] = {}
    for link in links:
        if not _is_catalog_grid_item(seed_url, link):
            continue
        m = _parse_catalog_grid_item(normalize_url(link.get("url", "")))
        if m:
            seg = m.group("seg").lower()
            counts[seg] = counts.get(seg, 0) + 1
    return [seg for seg, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def _catalog_grid_listing_urls(seed_url: str, links: list[dict] | None = None) -> list[str]:
    """Candidate catalog listing pages — inferred from dominant grid segment."""
    parsed = urlparse(seed_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    urls: list[str] = [seed_url]

    ranked = _catalog_grid_segments_from_links(seed_url, links or [])
    if not ranked:
        path = parsed.path.rstrip("/")
        listing = _CATALOG_GRID_LISTING_RE.search(path + "/")
        if listing:
            ranked = [listing.group("seg").lower()]
        elif path.count("/") <= 1:
            ranked = list(_CATALOG_GRID_SEGMENTS)

    for seg in ranked[:4]:
        urls.append(f"{base}/{seg}")
    urls.append(f"{base}/summer-camps")
    return list(dict.fromkeys(normalize_url(u) for u in urls if u))


def _catalog_grid_item_count(url: str, links: list[dict]) -> int:
    return sum(1 for link in links if _is_catalog_grid_item(url, link))


def _looks_like_catalog_grid(url: str, links: list[dict], page_text: str) -> bool:
    """True when same host exposes many /{segment}/{slug} catalog detail URLs."""
    if _looks_like_woocommerce(url, links, page_text):
        return False
    count = _catalog_grid_item_count(url, links)
    if count >= _CATALOG_GRID_MIN_ITEMS:
        return True
    low = (page_text or "").lower()
    if count >= _CATALOG_GRID_MIN_ITEMS_WITH_COUNTER and re.search(
        r"results?\s*:\s*\d+|\d+\s+courses?|\d+\s+programs?",
        low,
    ):
        return True
    return False


def _looks_like_woocommerce(url: str, links: list[dict], page_text: str) -> bool:
    """True when the site is a WooCommerce shop even if this page has no products yet."""
    if _woo_product_links(url, links):
        return True
    if _woo_category_links(url, links):
        return True
    low = (page_text or "").lower()
    if _WOO_SIGNATURE_RE.search(low):
        return True
    for l in links:
        u = (l.get("url") or "").lower()
        if _WOO_SIGNATURE_RE.search(u):
            return True
    return False


def _extract_embedded_platform_urls(page_text: str, links: list[dict]) -> list[str]:
    found: list[str] = []
    for blob in [page_text or ""] + [l.get("url", "") for l in links]:
        for m in _EMBED_PLATFORM_RE.finditer(blob):
            start = max(0, m.start() - 40)
            chunk = blob[start : m.end() + 60]
            for url_m in re.finditer(r"https?://[^\s\"'<>]+", chunk, re.I):
                found.append(url_m.group(0))
    return list(dict.fromkeys(found))


def detect_platform(url: str, links: list[dict], page_text: str = "") -> str:
    """Best-effort platform id from the provider URL, its outbound link hosts,
    and (lightly) its page text. Structured/portal platforms win over builders.
    """
    base_host = urlparse(url).netloc.lower()
    link_hosts = _hosts_of(links)
    haystacks = [base_host, *link_hosts]

    if is_community_ed_host(url):
        return COMMUNITY_ED

    if _YMCA_HOST_RE.search(base_host):
        return YMCA

    # 1) external registration platforms (highest signal)
    for platform, subs in _HOST_SIGNATURES:
        if any(any(s in h for h in haystacks) for s in subs):
            return platform

    # Embedded WebTrac/Daxko/Veracross in marketing HTML
    for embed in _extract_embedded_platform_urls(page_text, links):
        if "myvscloud" in embed.lower() or "webtrac" in embed.lower():
            return WEBTRAC
        if "veracross" in embed.lower():
            return VERACROSS
        if "daxko" in embed.lower():
            return DAXKO

    # 2) Course-grid catalogs (iD Tech /courses, etc.)
    if _looks_like_catalog_grid(url, links, page_text):
        return CATALOG_GRID

    # 3) WooCommerce: products OR category/catalog pages on same host
    if _looks_like_woocommerce(url, links, page_text):
        return WOOCOMMERCE

    # 4) site builders
    low_text = (page_text or "").lower()
    for platform, subs in _BUILDER_HOST_SIGNATURES:
        if any(any(s in h for h in haystacks) for s in subs) or any(s in low_text for s in subs):
            return platform

    if re.search(r"wp-content", low_text) and not _WOO_SIGNATURE_RE.search(low_text):
        return WORDPRESS

    return CUSTOM


# --------------------------------------------------------------------------- #
# Fetch + pagination helpers (Playwright via crawl.py, lazy import)
# --------------------------------------------------------------------------- #
async def _fetch(
    url: str,
    tries: int = 3,
    *,
    caller: str = "_fetch",
    wait_until: str | None = None,
    kind: str = "",
) -> tuple[str, list[dict]]:
    from src.crawl import fetch_page_text_and_links
    from src import fetch_cache

    cached = fetch_cache.get(url, kind=kind)
    if cached is not None:
        return cached

    for attempt in range(tries):
        try:
            text, links = await fetch_page_text_and_links(
                url, caller=caller, wait_until=wait_until, kind=kind
            )
            fetch_cache.put(url, text, links, kind=kind)
            return text, links
        except Exception as exc:  # noqa: BLE001
            if attempt == tries - 1:
                logger.warning("fetch gave up on %s: %s", url, exc)
                return "", []
            await asyncio.sleep(1.5)
    return "", []


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #
def _clean_name(text: str, url: str) -> str:
    if not text:
        slug = url.rstrip("/").split("/")[-1]
        return slug.replace("-", " ").replace("_", " ").title()
    name = text.split("\n")[0].strip()
    name = re.sub(r"\$[\d,.]+.*$", "", name).strip()
    return name


_PRICE_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")
_DATE_RE = re.compile(
    r"\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:\s*[-–]\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?)?"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{1,2}",
    re.IGNORECASE,
)


def _woo_product_re(url: str) -> re.Pattern:
    # product detail under /product|class|event|camp — NOT generic /program/ hub pages
    return re.compile(
        r"/(?:product|class|event|camp)/[^/]+/?$",
        re.IGNORECASE,
    )


def _is_valid_woo_product(url: str, name: str = "") -> bool:
    path = urlparse(url).path.lower()
    slug = path.rstrip("/").split("/")[-1]
    if re.search(r"teens|children-classes|faq|membership|contact|donate", slug, re.I):
        return False
    if re.search(r"/program/", path):
        return bool(re.search(r"camp|summer|clinic", slug, re.I))
    return bool(_woo_product_re(url).search(path))


def _woo_product_links(url: str, links: list[dict]) -> list[dict]:
    host = urlparse(url).netloc.lower().replace("www.", "")
    out = []
    for l in links:
        u = l.get("url", "")
        h = urlparse(u).netloc.lower().replace("www.", "")
        if h == host and _is_valid_woo_product(u, l.get("text", "")):
            out.append(l)
    return out


async def _paginate(
    base_url: str,
    link_filter,
    *,
    page_param: str = "/page/{n}/",
    max_pages: int = 20,
) -> list[dict]:
    """Walk WooCommerce-style pagination collecting links that pass link_filter.

    Stops when a page yields no new matching links. Returns deduped link dicts.
    """
    seen: set[str] = set()
    out: list[dict] = []
    page = 1
    base = base_url.rstrip("/")
    while page <= max_pages:
        url = base_url if page == 1 else f"{base}{page_param.format(n=page)}"
        _, links = await _fetch(url)
        matches = [l for l in links if link_filter(l)]
        new = 0
        for l in matches:
            nu = normalize_url(l.get("url", ""))
            if nu and nu not in seen:
                seen.add(nu)
                out.append(l)
                new += 1
        if new == 0:
            break
        page += 1
    if page > max_pages:
        logger.info("pagination cap (%d pages) reached for %s", max_pages, base_url)
    return out


def _catalog_root_url(url: str) -> str | None:
    """First path segment as catalog root, e.g. /lexplorations/find-a-class -> /lexplorations/."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    skip_roots = {"shop", "class", "product", "wp-content", "info", "programs"}
    if parts[0].lower() in skip_roots:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/{parts[0]}/"


def _catalog_path_prefix(url: str) -> str | None:
    """URL path prefix for scoped catalogs, e.g. /lexplorations/."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    skip_roots = {"shop", "class", "product", "wp-content", "info", "programs"}
    if parts[0].lower() in skip_roots:
        return None
    return f"/{parts[0]}/"


def _category_in_catalog_scope(cat_url: str, prefix: str | None) -> bool:
    """When seeded under a catalog prefix, ignore site-wide /shop/ and /class-category/."""
    if not prefix:
        return True
    path = urlparse(cat_url).path.lower()
    if path.rstrip("/") in ("/shop", prefix.rstrip("/") + "/shop"):
        return False
    return path.startswith(prefix.lower())


async def adapter_catalog_grid(url: str, links: list[dict], page_text: str) -> list[dict]:
    """Harvest per-item URLs from any multi-course catalog grid on one host."""
    collected: dict[str, dict] = {}
    dominant_segments = _catalog_grid_segments_from_links(url, links)

    def absorb(link_list: list[dict]) -> None:
        for link in link_list:
            if not _is_catalog_grid_item(url, link):
                continue
            nu = normalize_url(link.get("url", ""))
            if not nu:
                continue
            if dominant_segments:
                m = _parse_catalog_grid_item(nu)
                if m and m.group("seg").lower() not in dominant_segments[:2]:
                    continue
            name = _clean_name(link.get("text", ""), nu)
            slug = (m.group("slug") if (m := _parse_catalog_grid_item(nu)) else "").lower()
            blob = f"{slug} {name.lower()}"
            if _CATALOG_GRID_SLUG_DENY.search(blob) and not _CATALOG_GRID_SLUG_REQUIRE.search(blob):
                continue
            if name.lower() in {
                "virtual",
                "on-campus",
                "on campus",
                "website",
                "learn more",
                "register",
                "sign up",
            }:
                name = _clean_name("", nu)
            if nu not in collected or len(name) > len(collected[nu]["name"]):
                collected[nu] = {"url": nu, "name": name, "text": link.get("text", "")}

    absorb(links)
    for listing_url in _catalog_grid_listing_urls(url, links):
        if normalize_url(listing_url) == normalize_url(url):
            continue
        _, more_links = await _fetch(listing_url)
        absorb(more_links)

    sessions: list[dict] = []
    for item in collected.values():
        price = ""
        m = _PRICE_RE.search(item["text"])
        if m:
            price = m.group(0)
        d = _DATE_RE.search(item["name"]) or _DATE_RE.search(item["text"])
        low = item["url"].lower()
        kind = "session"
        if "/virtual" in low or "virtual-" in low or low.endswith("/virtual"):
            kind = "session"
        sessions.append(
            make_session(
                item["name"],
                item["url"],
                platform=CATALOG_GRID,
                price=price,
                dates=d.group(0) if d else "",
                source_url=url,
                kind=kind,
            )
        )
    logger.info("catalog_grid: %d course(s) from %s", len(sessions), _catalog_grid_host(url))
    return sessions


async def _harvest_program_slug_catalog(url: str, links: list[dict]) -> list[dict]:
    """Sites like vikingcamps.com list camps under /program/{slug}, not WooCommerce."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    base = f"{parsed.scheme}://{parsed.netloc}"
    collected: dict[str, dict] = {}

    def absorb(link_list: list[dict]) -> None:
        for link in link_list:
            u = normalize_url(link.get("url", ""))
            if not u or urlparse(u).netloc.lower().replace("www.", "") != host:
                continue
            if not _PROGRAM_SLUG_RE.match(urlparse(u).path):
                continue
            slug = u.rstrip("/").split("/")[-1].lower()
            from src.camp_discovery import score_camp_candidate

            if host not in _PROGRAM_CATALOG_HOSTS and score_camp_candidate(
                u, link.get("text", "")
            ) < 2:
                continue
            name = _clean_name(link.get("text", ""), u)
            if u not in collected or len(name) > len(collected[u]["name"]):
                collected[u] = {"url": u, "name": name, "text": link.get("text", "")}

    absorb(links)
    for seed in (url, f"{base}/summer", f"{base}/programs", base):
        if normalize_url(seed) == normalize_url(url) and seed != url:
            continue
        _, more = await _fetch(seed)
        absorb(more)

    return [
        make_session(
            item["name"],
            item["url"],
            platform=WOOCOMMERCE,
            source_url=url,
        )
        for item in collected.values()
    ]


async def adapter_woocommerce(url: str, links: list[dict], page_text: str) -> list[dict]:
    """Enumerate WooCommerce products. Follows category pages + pagination so we
    catch items hidden behind 'classes with availability' filters."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    program_hits = sum(
        1
        for l in links
        if urlparse(l.get("url", "")).netloc.lower().replace("www.", "") == host
        and _PROGRAM_SLUG_RE.match(urlparse(l.get("url", "")).path)
    )
    if host in _PROGRAM_CATALOG_HOSTS or program_hits >= 3:
        program_sessions = await _harvest_program_slug_catalog(url, links)
        if program_sessions:
            return program_sessions

    pat = _woo_product_re(url)
    max_categories = 25
    max_pages_per_category = 15

    def is_product(l):
        u = l.get("url", "")
        h = urlparse(u).netloc.lower().replace("www.", "")
        name = _clean_name(l.get("text", ""), u)
        return h == host and _is_valid_woo_product(u, name)

    def is_category_link(l):
        u = l.get("url", "")
        h = urlparse(u).netloc.lower().replace("www.", "")
        return h == host and _WOO_CATEGORY_RE.search(urlparse(u).path)

    collected: dict[str, dict] = {}

    def absorb(link_list):
        for l in link_list:
            if not is_product(l):
                continue
            nu = normalize_url(l.get("url", ""))
            name = _clean_name(l.get("text", ""), l.get("url", ""))
            if nu and (nu not in collected or len(name) > len(collected[nu]["name"])):
                collected[nu] = {"url": nu, "name": name, "text": l.get("text", "")}

    absorb(links)

    catalog_prefix = _catalog_path_prefix(url)
    cat_links: list[str] = [
        l["url"] for l in links if is_category_link(l) and _category_in_catalog_scope(l["url"], catalog_prefix)
    ]

    # Catalog root: discover week/category pages not linked from find-a-class alone.
    root = _catalog_root_url(url)
    if root:
        _, root_links = await _fetch(root)
        cat_links.extend(
            l["url"]
            for l in root_links
            if is_category_link(l) and _category_in_catalog_scope(l["url"], catalog_prefix)
        )
        absorb(root_links)

    if not catalog_prefix:
        parsed = urlparse(url)
        shop_root = f"{parsed.scheme}://{parsed.netloc}/shop/"
        _, shop_links = await _fetch(shop_root)
        cat_links.extend(l["url"] for l in shop_links if is_category_link(l))

    cat_links = list(dict.fromkeys(cat_links))[:max_categories]
    logger.info(
        "woocommerce: paginating %d category page(s) for %s",
        len(cat_links),
        host,
    )
    for cat in cat_links:
        paged = await _paginate(cat, is_product, max_pages=max_pages_per_category)
        absorb(paged)

    sessions = []
    for item in collected.values():
        price = ""
        m = _PRICE_RE.search(item["text"])
        if m:
            price = m.group(0)
        d = _DATE_RE.search(item["name"]) or _DATE_RE.search(item["text"])
        sessions.append(
            make_session(
                item["name"],
                item["url"],
                platform=WOOCOMMERCE,
                price=price,
                dates=d.group(0) if d else "",
                source_url=url,
            )
        )
    return sessions


async def adapter_community_ed(url: str, links: list[dict], page_text: str) -> list[dict]:
    """Lexplorations / community-ed WooCommerce — scoped catalog, never full /shop/."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    catalog_prefix = resolve_catalog_prefix(url) or "/lexplorations/"
    max_categories = MAX_COMMUNITY_ED_CATEGORIES
    max_pages_per_category = MAX_COMMUNITY_ED_PAGES_PER_CATEGORY

    def is_product(l):
        u = l.get("url", "")
        h = urlparse(u).netloc.lower().replace("www.", "")
        name = _clean_name(l.get("text", ""), u)
        return h == host and _is_valid_woo_product(u, name) and product_allowed(u, name, catalog_prefix)

    def is_category_link(l):
        u = l.get("url", "")
        h = urlparse(u).netloc.lower().replace("www.", "")
        return h == host and _WOO_CATEGORY_RE.search(urlparse(u).path) and category_allowed(u, catalog_prefix)

    collected: dict[str, dict] = {}

    def absorb(link_list):
        for l in link_list:
            if not is_product(l):
                continue
            nu = normalize_url(l.get("url", ""))
            name = _clean_name(l.get("text", ""), l.get("url", ""))
            if nu and (nu not in collected or len(name) > len(collected[nu]["name"])):
                collected[nu] = {"url": nu, "name": name, "text": l.get("text", "")}

    absorb(links)

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    find_a_class = f"{base}{catalog_prefix.rstrip('/')}/find-a-class"
    cat_links: list[str] = [
        l["url"] for l in links if is_category_link(l)
    ]
    # Always seed scoped catalog listing — never /shop/
    for seed in (
        find_a_class,
        f"{base}{catalog_prefix.rstrip('/')}/",
    ):
        _, seed_links = await _fetch(seed)
        cat_links.extend(l["url"] for l in seed_links if is_category_link(l))
        absorb(seed_links)

    paged_products = await _paginate(find_a_class, is_product, max_pages=max_pages_per_category)
    absorb(paged_products)

    cat_links = list(dict.fromkeys(cat_links))[:max_categories]
    logger.info("community_ed: paginating %d category page(s) for %s", len(cat_links), host)
    for cat in cat_links:
        paged = await _paginate(cat, is_product, max_pages=max_pages_per_category)
        absorb(paged)

    sessions = []
    for item in collected.values():
        price = ""
        m = _PRICE_RE.search(item["text"])
        if m:
            price = m.group(0)
        d = _DATE_RE.search(item["name"]) or _DATE_RE.search(item["text"])
        sessions.append(
            make_session(
                item["name"],
                item["url"],
                platform=COMMUNITY_ED,
                price=price,
                dates=d.group(0) if d else "",
                source_url=url,
            )
        )
    return sessions


async def adapter_ymca(url: str, links: list[dict], page_text: str) -> list[dict]:
    """YMCA marketing site -> discover embedded WebTrac/Daxko -> enumerate camps."""
    embeds = _extract_embedded_platform_urls(page_text, links)
    for embed in embeds:
        low = embed.lower()
        if "myvscloud" in low or "webtrac" in low:
            _, elinks = await _fetch(embed)
            sessions = await adapter_webtrac(embed, elinks, page_text)
            if sessions:
                return sessions
        if "daxko" in low:
            sessions = await adapter_daxko(
                embed,
                links + [{"url": embed, "text": ""}],
                page_text,
            )
            if sessions:
                return sessions

    # Build canonical WebTrac camp search from any myvscloud link on page
    for l in links:
        u = l.get("url", "")
        if "myvscloud.com" not in u.lower():
            continue
        p = urlparse(u)
        if "/webtrac/" in p.path.lower():
            base = u[: u.lower().index("/webtrac/")] + "/webtrac/web/"
            cat = f"{base}search.html?module=AR&type=CAMP"
            _, cat_links = await _fetch(cat)
            sessions = await adapter_webtrac(cat, cat_links, page_text)
            if sessions:
                return sessions

    for l in links:
        u = l.get("url", "")
        if "daxko.com" in u.lower():
            sessions = await adapter_daxko(u, links, page_text)
            if sessions:
                return sessions

    return _portal_links(url, links, ("myvscloud.com",), WEBTRAC)


_WEBTRAC_BAD_NAME_RE = re.compile(r"^(item details|add to (cart|selection|wishlist)|share|more info)", re.I)


async def adapter_webtrac(url: str, links: list[dict], page_text: str) -> list[dict]:
    """WebTrac/myvscloud: one session per iteminfo?FMID= in the CAMP module.

    We target the canonical camp catalog (module=AR&type=CAMP) rather than
    whatever 'register' link happens to appear first (which may be a swim/PM
    catalog), and union any camp-category catalogs we find on the page.
    """
    from src.camp_validator import extract_registration_sessions

    webtrac_links = [
        l.get("url", "")
        for l in links
        if "myvscloud.com" in l.get("url", "").lower() or "webtrac" in l.get("url", "").lower()
    ]

    catalogs: list[str] = []
    # 1) canonical full camp catalog, derived from the WebTrac base host
    for wl in webtrac_links:
        p = urlparse(wl)
        if "/webtrac/" in p.path.lower():
            base = wl[: wl.lower().index("/webtrac/")] + "/webtrac/web/"
            catalogs.append(f"{base}search.html?module=AR&type=CAMP")
            break
    # 2) any camp-specific catalog links already on the page (e.g. Specialty Camps)
    for wl in webtrac_links:
        low = wl.lower()
        if "search.html" in low and ("type=camp" in low.replace(" ", "") or "category=" in low and "camp" in low):
            catalogs.append(wl)

    catalogs = list(dict.fromkeys(catalogs)) or webtrac_links[:1]

    by_fmid: dict[str, dict] = {}
    for cat in catalogs[:5]:
        _, cat_links = await _fetch(cat)
        parsed_rows = extract_registration_sessions(cat_links)
        if not parsed_rows:
            from src.camp_validator import extract_webtrac_search_results
            parsed_rows = extract_webtrac_search_results(cat_links)
        for r in parsed_rows:
            # camp module only; drop generic/non-camp item rows
            if "module=ar" not in r["register_url"].lower():
                continue
            if not r["name"] or _WEBTRAC_BAD_NAME_RE.match(r["name"]):
                continue
            by_fmid.setdefault(r["id"], {**r, "source": cat})

    return [
        make_session(
            r["name"],
            r["register_url"],
            info_url=r["register_url"],
            platform=WEBTRAC,
            dates=r.get("dates", ""),
            source_url=r.get("source", url),
        )
        for r in by_fmid.values()
    ]


async def adapter_myrec(url: str, links: list[dict], page_text: str) -> list[dict]:
    """MyRec.com: each camp/program is program_details.aspx?ProgramID=NNNN.
    The activities listing page links to them by name."""
    # Make sure we're looking at an activities listing; if not, try to find one.
    def program_links(link_list):
        out = {}
        for l in link_list:
            u = l.get("url", "")
            if "program_details.aspx" not in u.lower():
                continue
            pid = (parse_qs(urlparse(u).query).get("ProgramID") or parse_qs(urlparse(u).query).get("programid") or [""])[0]
            name = _clean_name(l.get("text", ""), u)
            key = pid or normalize_url(u)
            if key and (key not in out or len(name) > len(out[key]["name"])):
                out[key] = {"url": u, "name": name}
        return out

    found = program_links(links)
    # MyRec detail/landing pages list few or no programs; always also enumerate
    # the host's canonical activities listing(s), which carry the full catalog.
    parsed = urlparse(url)
    host_base = f"{parsed.scheme}://{parsed.netloc}"
    canonical = [
        f"{host_base}/info/activities/activities.aspx",
        f"{host_base}/info/activities/default.aspx?type=activities",
        f"{host_base}/info/activities/default.aspx?type=camps",
    ]
    same_host_listings = [
        l["url"]
        for l in links
        if urlparse(l.get("url", "")).netloc.lower() == parsed.netloc.lower()
        and re.search(r"activities", l.get("url", ""), re.I)
        and "program_details" not in l.get("url", "").lower()
    ]
    for lp in list(dict.fromkeys(canonical + same_host_listings))[:6]:
        _, ll = await _fetch(lp)
        found.update(program_links(ll))

    return [
        make_session(
            v["name"],
            v["url"],
            info_url=v["url"],
            platform=MYREC,
            source_url=url,
        )
        for v in found.values()
    ]


def _portal_links(url: str, links: list[dict], host_subs: tuple[str, ...], platform: str) -> list[dict]:
    """Generic portal adapter: surface links pointing into the external
    registration host. Per-session links if present, else the portal entry."""
    hits = []
    seen = set()
    for l in links:
        u = l.get("url", "")
        if any(s in u.lower() for s in host_subs):
            nu = normalize_url(u)
            if nu in seen:
                continue
            seen.add(nu)
            hits.append(
                make_session(
                    _clean_name(l.get("text", ""), u),
                    u,
                    platform=platform,
                    source_url=url,
                    kind="session" if re.search(r"camp|program|schedule|class|session|activity", u, re.I) else "portal",
                )
            )
    return hits


async def adapter_sawyer(url, links, page_text):
    """Sawyer/hisawyer: try to parse activity links from the schedule page."""
    portal_hits = _portal_links(url, links, ("hisawyer.com",), SAWYER)
    if not portal_hits:
        return portal_hits

    sessions: list[dict] = []
    seen: set[str] = set()
    for hit in portal_hits:
        _, sawyer_links = await _fetch(hit["register_url"])
        for l in sawyer_links:
            u = l.get("url", "")
            if "hisawyer.com" not in u.lower():
                continue
            # activity detail URLs often contain /activities/ or /catalog/
            if not re.search(r"/activit|/catalog|/class|/camp|/program|/session", u, re.I):
                continue
            name = _clean_name(l.get("text", ""), u)
            if not name or len(name) < 3:
                continue
            nu = normalize_url(u)
            if nu in seen:
                continue
            seen.add(nu)
            sessions.append(
                make_session(
                    name,
                    u,
                    platform=SAWYER,
                    source_url=url,
                    kind="session",
                )
            )

    if sessions:
        return sessions
    # JS-only schedule: fall back to portal entry with provider context in name
    best = portal_hits[0]
    if not best["name"] or best["name"].lower() in ("register", "sign up", "enroll"):
        slug = urlparse(url).path.strip("/").split("/")[-1] or "programs"
        best = {**best, "name": slug.replace("-", " ").title() + " (Sawyer registration)"}
    return [best]


async def adapter_campbrain(url, links, page_text):
    return _portal_links(url, links, ("campbrainregistration.com", "campbrain.com"), CAMPBRAIN)


async def adapter_arbiter(url, links, page_text):
    return _portal_links(url, links, ("arbitersports.com",), ARBITER)


async def adapter_active(url, links, page_text):
    return _portal_links(url, links, ("activecommunities.com", "active.com"), ACTIVE)


async def adapter_communitypass(url, links, page_text):
    return _portal_links(url, links, ("communitypass.net",), COMMUNITYPASS)


_DAXKO_DETAIL_RE = re.compile(
    r"ProgramDetail\.mvc|OfferingDetail\.mvc|program_id=\d+|offering_id=\d+",
    re.I,
)
_DAXKO_CAMP_NOISE_RE = re.compile(
    r"swim\s*test|life\s*jacket|pre[\s-]?camp\s*test|fitting|membership|donat",
    re.I,
)


def _extract_daxko_sessions(links: list[dict], source_url: str) -> list[dict]:
    """Parse Daxko ProgramsV2 search/detail links into per-offering sessions."""
    by_key: dict[str, dict] = {}
    for link in links:
        u = link.get("url", "")
        if "daxko.com" not in u.lower():
            continue
        text = (link.get("text") or "").strip()
        low_u = u.lower()
        is_detail = bool(_DAXKO_DETAIL_RE.search(u))
        has_camp_signal = bool(re.search(r"camp|summer|cit\b|lit\b|ages?\s*\d", text, re.I))
        if not is_detail and not has_camp_signal:
            continue
        if text and _DAXKO_CAMP_NOISE_RE.search(text):
            continue
        name = _clean_name(text, u)
        if not name or len(name) < 4:
            continue
        if _DAXKO_CAMP_NOISE_RE.search(name):
            continue
        qs = parse_qs(urlparse(u).query)
        key = (
            (qs.get("program_id") or qs.get("offering_id") or [""])[0]
            or normalize_url(u)
        )
        entry = by_key.setdefault(
            key,
            {"name": name, "register_url": normalize_url(u) or u, "source": source_url},
        )
        if len(name) > len(entry["name"]):
            entry["name"] = name
    return [
        make_session(
            e["name"],
            e["register_url"],
            platform=DAXKO,
            source_url=e["source"],
        )
        for e in by_key.values()
    ]


async def adapter_daxko(url: str, links: list[dict], page_text: str) -> list[dict]:
    """Daxko YMCA/club ops — drill into ProgramsV2 search results."""
    portal_urls: list[str] = []
    for l in links:
        u = l.get("url", "")
        if "daxko.com" in u.lower():
            portal_urls.append(u)
    if "daxko.com" in url.lower():
        portal_urls.insert(0, url)
    portal_urls = list(dict.fromkeys(portal_urls))

    sessions: list[dict] = []
    seen_regs: set[str] = set()
    for portal in portal_urls[:4]:
        _, plinks = await _fetch(portal)
        for s in _extract_daxko_sessions(plinks, portal):
            if s["register_url"] in seen_regs:
                continue
            seen_regs.add(s["register_url"])
            sessions.append(s)
        # Grouped search pages (e.g. "Ages 5/6") — follow camp-category anchors.
        for l in plinks:
            text = (l.get("text") or "").strip()
            u = l.get("url", "")
            if "daxko.com" not in u.lower():
                continue
            if not re.search(r"summer\s*camp|boroughs\s*summer|ages?\s*\d", text, re.I):
                continue
            _, group_links = await _fetch(u)
            for s in _extract_daxko_sessions(group_links, u):
                if s["register_url"] in seen_regs:
                    continue
                seen_regs.add(s["register_url"])
                sessions.append(s)

    if sessions:
        return sessions
    return _portal_links(url, links, ("daxko.com",), DAXKO)


async def adapter_veracross(url: str, links: list[dict], page_text: str) -> list[dict]:
    """Veracross ProgramRegistration — school summer/sport camp catalogs."""
    seeds: list[str] = []
    for l in links:
        u = l.get("url", "")
        if "veracross.com" not in u.lower():
            continue
        if re.search(r"ProgramRegistration|/programs?/", u, re.I):
            seeds.append(u)
    for embed in _extract_embedded_platform_urls(page_text, links):
        if "veracross" in embed.lower():
            seeds.append(embed)
    seeds = list(dict.fromkeys(seeds))

    collected: dict[str, dict] = {}
    for seed in seeds[:6]:
        _, vlinks = await _fetch(seed)
        for l in vlinks:
            u = l.get("url", "")
            if "veracross.com" not in u.lower():
                continue
            if not re.search(
                r"ProgramRegistration|program_id=|/sport|/camp|/summer",
                u,
                re.I,
            ):
                continue
            name = _clean_name(l.get("text", ""), u)
            if not name or len(name) < 3:
                continue
            nu = normalize_url(u)
            if nu not in collected or len(name) > len(collected[nu]["name"]):
                collected[nu] = {"url": nu, "name": name}

    return [
        make_session(item["name"], item["url"], platform=VERACROSS, source_url=url)
        for item in collected.values()
    ]


async def adapter_ultracamp(url, links, page_text):
    return _portal_links(url, links, ("ultracamp.com",), ULTRACAMP)


async def adapter_recdesk(url, links, page_text):
    return _portal_links(url, links, ("recdesk.com",), RECDESK)


async def adapter_civicrec(url, links, page_text):
    return _portal_links(url, links, ("civicrec", "civicplus"), CIVICREC)


async def adapter_perfectmind(url, links, page_text):
    return _portal_links(url, links, ("perfectmind",), PERFECTMIND)


async def adapter_jackrabbit(url, links, page_text):
    return _portal_links(url, links, ("jackrabbitclass.com",), JACKRABBIT)


async def adapter_campdoc(url, links, page_text):
    return _portal_links(url, links, ("campdoc.com",), CAMPDOC)


async def adapter_campminder(url, links, page_text):
    return _portal_links(url, links, ("campminder.com",), CAMPMINDER)


async def adapter_llm(url: str, links: list[dict], page_text: str, town_hint: str = "") -> list[dict]:
    """Fallback for marketing-site builders: ask the local LLM to enumerate the
    camps described in the page prose, then match each to a link."""
    from src.camp_validator import extract_camp_sessions, should_llm_extract
    from src.enrollment_signals import attach_inline_verification, verify_registrable
    from src.registration import is_registration_platform_url

    from src import session_log

    # roadmap2 Phase 4: never fabricate from a login/empty/thin page.
    ok, why = should_llm_extract(page_text)
    if not ok:
        session_log.llm_extract_rejected(name="", reason=f"page not extractable ({why})")
        return []

    raw = extract_camp_sessions(url, page_text=page_text, page_links=links, town_hint=town_hint)
    sessions = []
    for c in raw:
        reg = c.get("register_urls") or []
        register_url = reg[0] if reg else ""
        name = c.get("name", "")
        if not register_url:
            session_log.llm_extract_rejected(name=name, reason="no registration link matched")
            continue
        same_marketing_page = (
            register_url.rstrip("/") == url.rstrip("/")
            and not is_registration_platform_url(register_url)
        )
        if same_marketing_page:
            # P4.2: an info page whose only "register" link is itself can still be a
            # valid single-page enroll target. Verify it instead of rejecting outright:
            # if the page carries an on-page register CTA (cart/price/parent_ready),
            # keep it with info_url == register_url and the verdict from signals.
            sig = verify_registrable(url, page_text)
            if not (sig.has_cart_cta or sig.auto_verdict == "parent_ready"):
                session_log.llm_extract_rejected(
                    name=name,
                    reason="only link is the same marketing page (no register CTA on page)",
                )
                continue
            session_log.llm_extract_kept(name=name, register_url=url)
            kept = make_session(
                name,
                url,
                info_url=url,
                platform="llm",
                ages=c.get("ages", ""),
                dates=c.get("dates", ""),
                source_url=url,
                kind="session",
            )
            sessions.append(attach_inline_verification(kept, url, page_text, session_name=name))
            continue
        session_log.llm_extract_kept(name=name, register_url=register_url)
        sessions.append(
            make_session(
                name,
                register_url or url,
                platform="llm",
                ages=c.get("ages", ""),
                dates=c.get("dates", ""),
                source_url=url,
                kind="session" if reg and is_registration_platform_url(reg[0]) else "portal",
            )
        )
    return sessions


_HEAVY_ADAPTER_PLATFORMS = frozenset({WOOCOMMERCE, COMMUNITY_ED})
_heavy_adapter_sem: asyncio.Semaphore | None = None


def _heavy_sem() -> asyncio.Semaphore:
    global _heavy_adapter_sem
    if _heavy_adapter_sem is None:
        from config.settings import SETTINGS

        _heavy_adapter_sem = asyncio.Semaphore(int(SETTINGS.get("b5_heavy_adapter_concurrency", 1)))
    return _heavy_adapter_sem


async def _run_adapter(platform: str, url: str, links: list[dict], page_text: str) -> list[dict]:
    from src import session_log

    adapter = _ADAPTERS.get(platform)
    if adapter is None:
        return []
    session_log.trace_adapter(platform=platform, url=url)
    if platform in _HEAVY_ADAPTER_PLATFORMS:
        async with _heavy_sem():
            return await adapter(url, links, page_text)
    return await adapter(url, links, page_text)


async def _trail_before_llm(url: str, town_hint: str) -> tuple[str, list[dict], str]:
    """Short focused crawl when structured adapter finds nothing."""
    from config.settings import SETTINGS
    from src.camp_validator import make_link_follow_gate
    from src.crawl import walk_site

    from src import session_log

    if not SETTINGS.get("b5_trail_before_llm"):
        return "", [], url
    pages = int(SETTINGS.get("b5_trail_pages", 8))
    session_log.trail_start(max_pages=pages)
    walk = await walk_site(
        url,
        SETTINGS.get("focused_max_depth", 3),
        pages,
        focused=True,
        delay_seconds=SETTINGS.get("focused_delay_seconds", 1.5),
        stop_on_catalog=True,
        link_gate=make_link_follow_gate() if SETTINGS.get("ollama_link_follow") else None,
    )
    best = url
    best_score = 0
    from src.registration import registration_url_priority

    for link in walk.links:
        u = link.get("url", "")
        score = registration_url_priority(u)
        if score > best_score:
            best_score = score
            best = u
    session_log.trail_done(
        pages_visited=len(walk.page_text_by_url),
        links_found=len(walk.links),
        best_url=best,
        seed_url=url,
    )
    if best != url:
        session_log.trace_probe(url=best, label="trail-best-candidate")
        text, links = await _fetch(best, caller="trail_before_llm:best")
        return text, links, best
    return walk.page_text_by_url.get(normalize_url(url), ""), walk.links, url


_ADAPTERS = {
    WEBTRAC: adapter_webtrac,
    CATALOG_GRID: adapter_catalog_grid,
    WOOCOMMERCE: adapter_woocommerce,
    COMMUNITY_ED: adapter_community_ed,
    MYREC: adapter_myrec,
    YMCA: adapter_ymca,
    SAWYER: adapter_sawyer,
    CAMPBRAIN: adapter_campbrain,
    ARBITER: adapter_arbiter,
    ACTIVE: adapter_active,
    COMMUNITYPASS: adapter_communitypass,
    DAXKO: adapter_daxko,
    VERACROSS: adapter_veracross,
    ULTRACAMP: adapter_ultracamp,
    RECDESK: adapter_recdesk,
    CIVICREC: adapter_civicrec,
    PERFECTMIND: adapter_perfectmind,
    JACKRABBIT: adapter_jackrabbit,
    CAMPDOC: adapter_campdoc,
    CAMPMINDER: adapter_campminder,
}


def _apply_focus_llm_tiebreaker(
    kept: list[dict],
    dropped: list[dict],
    *,
    town_hint: str = "",
) -> tuple[list[dict], list[dict]]:
    """Re-check ambiguous heuristic drops with Ollama. Fail-closed: only an
    explicit keep=true recovers a session."""
    from config.settings import SETTINGS
    from src.camp_validator import verify_youth_summer
    from src.llm import OllamaError, is_available
    from src.relevance import is_ambiguous, is_hard_drop

    if not SETTINGS.get("ollama_focus_verify"):
        return kept, dropped

    ambiguous = [s for s in dropped if is_ambiguous(s.get("_focus_reason", ""))]
    if not ambiguous:
        return kept, dropped

    fail_open = bool(SETTINGS.get("b5_focus_verify_fail_open", True))

    def _camp_context(s: dict) -> bool:
        # Recoverable on model failure only when the row carries independent
        # evidence (age/date/price) or sits on a real registration platform —
        # never a blind keep-everything.
        from src.junk_audit import has_evidence
        from src.registration import is_registration_platform_url

        return has_evidence(s) or is_registration_platform_url(s.get("register_url", ""))

    if not is_available():
        from src import session_log

        session_log.llm_unavailable()
        if not fail_open:
            return kept, dropped
        # Fail OPEN: recover camp-context ambiguous drops the model can't judge.
        recovered, still = [], []
        for s in dropped:
            if (
                is_ambiguous(s.get("_focus_reason", ""))
                and not is_hard_drop(s.get("_focus_reason", ""))
                and _camp_context(s)
            ):
                recovered.append({**s, "_focus_reason": "llm-unavailable:fail-open"})
            else:
                still.append(s)
        return kept + recovered, still

    from src import session_log

    budget = int(SETTINGS.get("ollama_focus_verify_max_per_source", 45))
    consecutive_drop_limit = int(
        SETTINGS.get("ollama_focus_verify_consecutive_drop_limit", 20)
    )
    session_log.llm_tiebreaker_start(ambiguous_count=len(ambiguous), budget=budget)

    recovered: list[dict] = []
    still_dropped: list[dict] = []
    budget_left = budget
    consecutive_drops = 0
    stopped_early = False

    for s in dropped:
        reason = s.get("_focus_reason", "")
        if not is_ambiguous(reason) or is_hard_drop(reason):
            still_dropped.append(s)
            continue
        if budget_left <= 0:
            still_dropped.append(s)
            continue
        if consecutive_drops >= consecutive_drop_limit:
            still_dropped.append(s)
            stopped_early = True
            continue
        budget_left -= 1
        name = s.get("name", "")
        try:
            keep, llm_reason = verify_youth_summer(
                name,
                ages=s.get("ages", ""),
                dates=s.get("dates", ""),
                text=s.get("text", ""),
                town_hint=town_hint,
            )
        except OllamaError as exc:
            logger.warning("focus tie-breaker failed for %s: %s", name, exc)
            if fail_open and _camp_context(s):
                consecutive_drops = 0
                recovered.append({**s, "_focus_reason": "llm-error:fail-open"})
            else:
                still_dropped.append(s)
            continue
        if keep:
            consecutive_drops = 0
            s = {**s, "_focus_reason": f"llm-keep:{llm_reason[:40]}"}
            session_log.llm_tiebreaker_recovered(name=name, reason=llm_reason)
            recovered.append(s)
        else:
            consecutive_drops += 1
            s = {**s, "_focus_reason": f"llm-drop:{llm_reason[:40]}"}
            session_log.llm_tiebreaker_confirmed_drop(name=name, reason=llm_reason)
            still_dropped.append(s)

    if budget_left <= 0:
        remaining = sum(
            1
            for s in still_dropped
            if is_ambiguous(s.get("_focus_reason", ""))
        )
        if remaining:
            session_log.llm_budget_exhausted(remaining=remaining)
    elif stopped_early:
        remaining = sum(
            1
            for s in still_dropped
            if is_ambiguous(s.get("_focus_reason", ""))
        )
        if remaining:
            session_log.llm_consecutive_drop_stop(
                consecutive=consecutive_drop_limit,
                remaining=remaining,
            )

    return kept + recovered, still_dropped


# --------------------------------------------------------------------------- #
# Unified dispatcher
# --------------------------------------------------------------------------- #
async def _enumerate_provider_v2(url: str, *, town_hint: str = "") -> dict:
    """Navigator v2 path: bounded recursive crawl behind b5_navigator_v2 flag."""
    from config.settings import SETTINGS
    from src import session_log
    from src.navigator import navigate_provider
    from src.relevance import is_ambiguous, is_hard_drop

    session_log.trace("enumerate_provider", f"seed={url} [navigator_v2]")
    sessions = await navigate_provider(url, town_hint=town_hint)
    platform = "navigator_v2"

    before_dedupe = len(sessions)
    seen, deduped = set(), []
    for s in sessions:
        key = s.get("register_url") or s.get("info_url") or ""
        if key and key not in seen:
            seen.add(key)
            deduped.append(s)
    session_log.dedupe(before=before_dedupe, after=len(deduped))

    dropped: list[dict] = []
    if SETTINGS.get("filter_to_focus"):
        from src.relevance import filter_sessions

        session_log.focus_filter_start(before=len(deduped))
        deduped, dropped = filter_sessions(deduped, SETTINGS.get("program_focus", "youth_summer"))
        hard_drops = sum(1 for s in dropped if is_hard_drop(s.get("_focus_reason", "")))
        ambiguous_drops = sum(1 for s in dropped if is_ambiguous(s.get("_focus_reason", "")))
        for s in deduped:
            session_log.focus_kept(name=s.get("name", ""), reason=s.get("_focus_reason", ""))
        for s in dropped:
            session_log.focus_dropped(name=s.get("name", ""), reason=s.get("_focus_reason", ""))
        session_log.focus_summary(
            kept=len(deduped),
            dropped=len(dropped),
            hard_drops=hard_drops,
            ambiguous_drops=ambiguous_drops,
        )
        deduped, dropped = _apply_focus_llm_tiebreaker(deduped, dropped, town_hint=town_hint)

    return {"url": url, "platform": platform, "sessions": deduped, "dropped": dropped}


async def enumerate_provider(url: str, *, town_hint: str = "") -> dict:
    """Detect the platform behind `url` and enumerate its camps.

    Returns {url, platform, sessions: list[Session]}. Falls back to the LLM
    extractor when a structured/portal adapter finds nothing.
    """
    from config.settings import SETTINGS as _ENUM_SETTINGS

    if _ENUM_SETTINGS.get("b5_navigator_v2"):
        return await _enumerate_provider_v2(url, town_hint=town_hint)

    from src import session_log
    from src.relevance import is_ambiguous, is_hard_drop

    session_log.trace("enumerate_provider", f"seed={url}")

    def _link_urls(link_list: list[dict]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for link in link_list:
            u = normalize_url(link.get("url", ""))
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    page_text, links = await _fetch(url, caller="enumerate_provider:seed")
    session_log.fetch_done(chars=len(page_text), link_count=len(links))
    all_links: list[dict] = list(links)
    session_log.links_pool(
        seed_url=url,
        stage="after seed page fetch",
        link_count=len(links),
        sample=_link_urls(links),
    )

    platform = detect_platform(url, links, page_text)
    session_log.platform_detected(platform=platform)

    sessions: list[dict] = []
    raw_count = 0
    if platform in _ADAPTERS:
        try:
            sessions = await _run_adapter(platform, url, links, page_text)
            raw_count = len(sessions)
            session_log.adapter_found(count=raw_count, platform=platform)
        except Exception as exc:  # noqa: BLE001
            logger.warning("adapter %s failed for %s: %s", platform, url, exc)
            session_log.adapter_found(count=0, platform=platform)

    if not sessions and any("veracross.com" in l.get("url", "").lower() for l in links):
        sessions = await adapter_veracross(url, links, page_text)
        if sessions:
            platform = VERACROSS
            session_log.adapter_found(count=len(sessions), platform=platform)

    from config.settings import SETTINGS as _SETTINGS

    trail_min = int(_SETTINGS.get("b5_trail_min_sessions", 3))

    if len(sessions) < trail_min and _SETTINGS.get("b5_agent_navigation", True):
        from src.camp_navigator import agent_navigate_provider

        agent_sessions, _agent_picks = await agent_navigate_provider(
            url,
            page_text,
            links,
            town_hint=town_hint,
        )
        if agent_sessions:
            sessions = sessions + agent_sessions
            platform = f"{platform}+agent_nav" if platform != CUSTOM else "agent_nav"
            session_log.adapter_found(count=len(agent_sessions), platform="agent_nav")

    if (
        len(sessions) < trail_min
        and _SETTINGS.get("b5_trail_before_llm")
        and platform
        in (
            CUSTOM,
            SQUARESPACE,
            WIX,
            WEEBLY,
            WORDPRESS,
            YMCA,
            WOOCOMMERCE,
        )
    ):
        page_text, links, trail_url = await _trail_before_llm(url, town_hint)
        all_links.extend(links)
        session_log.links_pool(
            seed_url=url,
            stage="after trail crawl",
            link_count=len(all_links),
            sample=_link_urls(all_links),
        )
        if trail_url != url:
            platform = detect_platform(trail_url, links, page_text)
            session_log.platform_detected(platform=platform)
            if platform in _ADAPTERS:
                try:
                    more = await _run_adapter(platform, trail_url, links, page_text)
                    if more:
                        sessions = sessions + more
                        session_log.adapter_found(count=len(more), platform=platform)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("trail adapter %s failed: %s", platform, exc)

    if len(sessions) < trail_min and platform in (
        CUSTOM,
        SQUARESPACE,
        WIX,
        WEEBLY,
        WORDPRESS,
    ):
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if re.search(r"summer|camp", parsed.path, re.I):
            for extra in (
                f"{base}/about/summer-programs",
                f"{base}/about/summer-programs/sport-camps",
                f"{base}/summer-programs",
            ):
                if normalize_url(extra) == normalize_url(url):
                    continue
                session_log.trace_probe(url=extra, label="school-summer-path")
                etext, elinks = await _fetch(extra, caller="enumerate_provider:summer-probe")
                all_links.extend(elinks)
                plat = detect_platform(extra, elinks, etext)
                if plat in _ADAPTERS:
                    try:
                        more = await _run_adapter(plat, extra, elinks, etext)
                        if more:
                            sessions = sessions + more
                            platform = plat
                            session_log.adapter_found(count=len(more), platform=platform)
                            if len(sessions) >= trail_min:
                                break
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("school summer probe %s failed: %s", plat, exc)
                if len(sessions) < trail_min and any(
                    "veracross.com" in l.get("url", "").lower() for l in elinks
                ):
                    more = await adapter_veracross(extra, elinks, etext)
                    if more:
                        sessions = sessions + more
                        platform = VERACROSS
                        session_log.adapter_found(count=len(more), platform=platform)
                        break

    if len(sessions) < trail_min:
        try:
            sessions = await adapter_llm(url, links, page_text, town_hint=town_hint)
            session_log.llm_page_extract(count=len(sessions))
            if sessions and platform in _ADAPTERS:
                platform = f"{platform}+llm"
            elif sessions:
                platform = platform if platform != CUSTOM else "llm"
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm fallback failed for %s: %s", url, exc)
            session_log.llm_page_extract(count=0)

    from src.camp_discovery import collect_camp_candidate_links, discover_verified_sessions
    from src import session_log as _session_log

    existing_regs = {s["register_url"] for s in sessions if s.get("register_url")}
    _cand_n = len(collect_camp_candidate_links(url, all_links))
    session_log.links_pool(
        seed_url=url,
        stage="before broad discovery (all sources merged)",
        link_count=len(all_links),
        sample=_link_urls(all_links),
    )
    discovered: list[dict] = []
    if _SETTINGS.get("b5_broad_discovery") and len(sessions) < trail_min:
        if _cand_n:
            _session_log.discovery_start(
                candidate_count=_cand_n,
                max_fetches=int(_SETTINGS.get("b5_discovery_max_fetches", 8)),
            )
        discovered = await discover_verified_sessions(
            url,
            all_links,
            town_hint=town_hint,
            existing_register_urls=existing_regs,
        )
        if discovered:
            session_log.discovery_found(count=len(discovered))
            sessions.extend(discovered)
            platform = f"{platform}+discovery" if platform != CUSTOM else "discovery"

    before_dedupe = len(sessions)
    seen, deduped = set(), []
    for s in sessions:
        key = s["register_url"]
        if key and key not in seen:
            seen.add(key)
            deduped.append(s)
    session_log.dedupe(before=before_dedupe, after=len(deduped))

    from config.settings import SETTINGS

    dropped: list[dict] = []
    if SETTINGS.get("filter_to_focus"):
        from src.relevance import filter_sessions

        session_log.focus_filter_start(before=len(deduped))
        deduped, dropped = filter_sessions(deduped, SETTINGS.get("program_focus", "youth_summer"))

        hard_drops = sum(1 for s in dropped if is_hard_drop(s.get("_focus_reason", "")))
        ambiguous_drops = sum(1 for s in dropped if is_ambiguous(s.get("_focus_reason", "")))
        for s in deduped:
            session_log.focus_kept(name=s.get("name", ""), reason=s.get("_focus_reason", ""))
        for s in dropped:
            session_log.focus_dropped(name=s.get("name", ""), reason=s.get("_focus_reason", ""))
        session_log.focus_summary(
            kept=len(deduped),
            dropped=len(dropped),
            hard_drops=hard_drops,
            ambiguous_drops=ambiguous_drops,
        )

        deduped, dropped = _apply_focus_llm_tiebreaker(deduped, dropped, town_hint=town_hint)

    return {"url": url, "platform": platform, "sessions": deduped, "dropped": dropped}
