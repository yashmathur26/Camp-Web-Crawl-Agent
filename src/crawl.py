import asyncio
import heapq
import itertools
import logging
import os
import re
from collections import defaultdict

# Use Chromium installed in venv (.local-browsers). Without this, Playwright
# looks in ~/Library/Caches/ms-playwright which may be empty on a fresh machine.
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import tldextract
from crawl4ai import (
    AsyncWebCrawler,
    BrowserConfig,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
    PruningContentFilter,
)

from config.settings import SETTINGS
from src.registration import (
    crawl_link_score,
    is_camp_catalog_url,
    is_registration_platform_url,
)
from src.urls import normalize_url, to_absolute

logger = logging.getLogger(__name__)


@dataclass
class WalkResult:
    links: list[dict] = field(default_factory=list)
    page_text_by_url: dict[str, str] = field(default_factory=dict)

_host_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
    lambda: asyncio.Semaphore(SETTINGS["crawl_concurrency"])
)
_pw_browser_sem: asyncio.Semaphore | None = None


def _playwright_sem() -> asyncio.Semaphore:
    """Cap concurrent headless Chrome instances (B.5 stability)."""
    global _pw_browser_sem
    if _pw_browser_sem is None:
        _pw_browser_sem = asyncio.Semaphore(int(SETTINGS.get("b5_max_browsers", 2)))
    return _pw_browser_sem


def _browser_config() -> BrowserConfig:
    """Headless browser defaults; verbose=False avoids Rich broken-pipe under nohup."""
    return BrowserConfig(
        headless=True,
        user_agent=SETTINGS["user_agent"],
        verbose=False,
    )


def _run_config(**overrides) -> CrawlerRunConfig:
    base = dict(
        page_timeout=SETTINGS["request_timeout"] * 1000,
        wait_until="domcontentloaded",
        markdown_generator=_MARKDOWN_GENERATOR,
        verbose=False,
    )
    base.update(overrides)
    return CrawlerRunConfig(**base)


def _is_js_render_host(url: str) -> bool:
    low = (url or "").lower()
    hosts = tuple(SETTINGS.get("b5_render_networkidle_hosts", ())) + tuple(
        SETTINGS.get("parent_verify_networkidle_hosts", ())
    )
    return any(h and h in low for h in hosts)


def fetch_wait_until(url: str, *, kind: str = "") -> str:
    """Choose Playwright wait_until: networkidle for JS registration portals.

    roadmap2 Phase 2: extend beyond register/portal kinds — JS-render hosts
    (Sawyer/MyRec/active.com/Daxko/…) need networkidle for *every* kind, because
    their camp catalog and detail content loads after domcontentloaded.
    """
    if kind in ("register", "portal"):
        return "networkidle"
    if _is_js_render_host(url):
        return "networkidle"
    return "domcontentloaded"


def is_thin_render(text: str) -> bool:
    """True if a render returned suspiciously little content."""
    return len((text or "").strip()) < int(SETTINGS.get("b5_render_thin_chars", 400))


# Prunes low-signal boilerplate (nav menus, footers) so `result.markdown.fit_markdown`
# carries the actual page content the LLM should judge — not the site menu.
_MARKDOWN_GENERATOR = DefaultMarkdownGenerator(
    content_filter=PruningContentFilter(threshold=0.48, threshold_type="fixed")
)
_robots_cache: dict[str, RobotFileParser | None] = {}


def _registered_domain(url: str) -> str:
    parsed = urlparse(url)
    ext = tldextract.extract(parsed.netloc)
    if not ext.domain or not ext.suffix:
        return parsed.netloc.lower()
    return f"{ext.domain}.{ext.suffix}".lower()


def _same_domain(url_a: str, url_b: str) -> bool:
    return _registered_domain(url_a) == _registered_domain(url_b)


def _get_robots_parser(url: str) -> RobotFileParser | None:
    if not SETTINGS["respect_robots_txt"]:
        return None
    domain = _registered_domain(url)
    if domain in _robots_cache:
        return _robots_cache[domain]
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        logger.debug("Could not read robots.txt for %s", domain)
        _robots_cache[domain] = None
        return None
    _robots_cache[domain] = rp
    return rp


def _is_allowed(url: str) -> bool:
    rp = _get_robots_parser(url)
    if rp is None:
        return True
    # Some sites ship robots.txt with User-agent:* but no rules; stdlib treats as deny-all.
    if not getattr(rp, "entries", None):
        return True
    try:
        return rp.can_fetch(SETTINGS["user_agent"], url)
    except Exception:
        return True


def _should_enqueue(start_url: str, child: str, depth: int, max_depth: int) -> bool:
    if depth >= max_depth:
        return False
    from src.crawl_scheduler import is_media_url

    if is_media_url(child):
        return False
    if _same_domain(start_url, child):
        return True
    if is_registration_platform_url(child):
        return True
    return not SETTINGS["stay_on_domain"]


_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _clean_for_llm(text: str) -> str:
    """Strip nav/boilerplate so the model sees camp content, not the menu.

    Rec-center page markdown is dominated by a repeated nav menu of markdown
    links, each carrying a long (often csrf-laden) URL that otherwise eats the
    whole truncation window. We drop image/link URLs but keep the visible link
    labels, collapse markdown bullet/heading punctuation, and squeeze
    whitespace — leaving readable content within the first few thousand chars."""
    text = _MD_IMAGE_RE.sub(" ", text)
    text = _MD_LINK_RE.sub(r"\1", text)  # keep the visible label, drop the URL
    text = re.sub(r"\s*[*|>#]+\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _augment_with_structured(result, text: str) -> str:
    """Prepend embedded schema.org JSON-LD program data (real names/dates/prices)
    to the page text when present, so JS/portal pages whose visible DOM is chrome
    still yield real program titles to downstream extraction (roadmap2 Phase 2)."""
    raw_html = getattr(result, "html", "") or ""
    if not raw_html:
        return text
    try:
        from src.structured_extract import extract_jsonld_events, structured_summary

        events = extract_jsonld_events(raw_html)
    except Exception:  # noqa: BLE001 — never let structured parsing break a fetch
        return text
    summary = structured_summary(events)
    return f"{summary}\n\n{text}" if summary else text


def _page_text_from_result(result) -> str:
    if not result or not getattr(result, "success", False):
        return ""
    # With a pruning markdown generator, result.markdown is a MarkdownGenerationResult
    # exposing .fit_markdown (boilerplate removed) and .raw_markdown.
    md = getattr(result, "markdown", None)
    for attr in ("fit_markdown", "raw_markdown"):
        val = getattr(md, attr, None)
        if isinstance(val, str) and val.strip():
            return _clean_for_llm(val)
    if isinstance(md, str) and md.strip():
        return _clean_for_llm(md)
    for attr in ("extracted_content", "cleaned_html"):
        raw = getattr(result, attr, None)
        if isinstance(raw, str) and raw.strip():
            return _clean_for_llm(raw)
    return ""


def _extract_links_from_result(base_url: str, result) -> list[dict]:
    links: list[dict] = []
    if not result or not getattr(result, "success", False):
        return links
    raw_links = getattr(result, "links", None) or {}
    for bucket in ("internal", "external"):
        for link in raw_links.get(bucket, []):
            href = link.get("href") or link.get("url") or ""
            text = link.get("text") or link.get("title") or ""
            absolute = to_absolute(base_url, href)
            if absolute:
                links.append({"url": absolute, "text": text})
    return links


async def fetch_rendered(
    url: str,
    *,
    wait: str = "networkidle",
    timeout_s: int = 20,
) -> str | None:
    """Rendered page HTML via Playwright; None on failure.

    Raw post-render HTML (not cleaned markdown) — for embed/widget discovery
    (Sawyer slugs, WebTrac iframes) that markdown cleaning strips out."""
    if not _is_allowed(url):
        return None
    domain = _registered_domain(url)
    sem = _host_semaphores[domain]
    browser_config = _browser_config()
    run_config = _run_config(wait_until=wait, page_timeout=int(timeout_s) * 1000)
    async with sem:
        await asyncio.sleep(float(SETTINGS.get("focused_delay_seconds", 1.5)))
        try:
            async with _playwright_sem():
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    result = await crawler.arun(url=url, config=run_config)
                    if not result or not getattr(result, "success", False):
                        return None
                    return getattr(result, "html", "") or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("fetch_rendered failed %s: %s", url, exc)
            return None


async def fetch_page_text(url: str, *, wait_until: str | None = None) -> str:
    """Shallow fetch of visible page text for LLM validation."""
    if not _is_allowed(url):
        return ""
    domain = _registered_domain(url)
    sem = _host_semaphores[domain]
    browser_config = _browser_config()
    wait = wait_until or fetch_wait_until(url)
    run_config = _run_config(wait_until=wait)
    fetch_delay = float(
        SETTINGS.get("ollama_validate_fetch_delay_seconds")
        or SETTINGS.get("focused_delay_seconds", 1.5)
    )
    async with sem:
        await asyncio.sleep(fetch_delay)
        try:
            async with _playwright_sem():
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    result = await crawler.arun(url=url, config=run_config)
                    return _page_text_from_result(result)
        except Exception as exc:
            logger.warning("Failed to fetch page text %s: %s", url, exc)
            return ""


async def fetch_page_text_and_links(
    url: str,
    *,
    caller: str = "fetch_page_text_and_links",
    wait_until: str | None = None,
    kind: str = "",
) -> tuple[str, list[dict]]:
    """One shallow fetch returning (clean_text, links). Used to enumerate camp
    sessions on a page and match each to its registration link."""
    from src import session_log

    session_log.trace_fetch_start(url=url, caller=caller)
    if not _is_allowed(url):
        session_log.trace_fetch_done(url=url, chars=0, link_count=0, error="robots.txt disallowed")
        return "", []
    domain = _registered_domain(url)
    sem = _host_semaphores[domain]
    browser_config = _browser_config()
    wait = wait_until or fetch_wait_until(url, kind=kind)
    run_config = _run_config(wait_until=wait)
    async with sem:
        await asyncio.sleep(SETTINGS["delay_seconds"])
        try:
            async with _playwright_sem():
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    result = await crawler.arun(url=url, config=run_config)
                    text = _page_text_from_result(result)
                    links = _extract_links_from_result(url, result)
                    text = _augment_with_structured(result, text)
                    # roadmap2 Phase 2: a JS host that came back thin probably
                    # hadn't finished rendering. Retry once, forcing networkidle
                    # plus a settle, before believing the page is empty.
                    if is_thin_render(text) and _is_js_render_host(url) and wait != "networkidle":
                        settle = float(SETTINGS.get("b5_render_settle_seconds", 1.2))
                        retry_config = _run_config(
                            wait_until="networkidle",
                            delay_before_return_html=settle,
                        )
                        session_log.trace_fetch_start(url=url, caller=f"{caller}:settle-retry")
                        result = await crawler.arun(url=url, config=retry_config)
                        text2 = _augment_with_structured(
                            result, _page_text_from_result(result)
                        )
                        links2 = _extract_links_from_result(url, result)
                        if len(text2.strip()) > len(text.strip()):
                            text, links = text2, links2
                    session_log.trace_fetch_done(
                        url=url, chars=len(text), link_count=len(links)
                    )
                    return text, links
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            session_log.trace_fetch_done(url=url, chars=0, link_count=0, error=str(exc))
            return "", []


async def get_links_on_page(url: str) -> list[dict]:
    if not _is_allowed(url):
        from src import harvest_log

        harvest_log.robots_disallow(url)
        return []

    domain = _registered_domain(url)
    sem = _host_semaphores[domain]
    browser_config = _browser_config()
    run_config = _run_config()

    async with sem:
        await asyncio.sleep(SETTINGS["delay_seconds"])
        try:
            async with _playwright_sem():
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    result = await crawler.arun(url=url, config=run_config)
                    return _extract_links_from_result(url, result)
        except Exception as exc:
            logger.warning("Failed to crawl %s: %s", url, exc)
            return []


async def harvest_guide_outbound(start_url: str, max_pages: int = 1) -> list[dict]:
    """Fetch a parent-guide page (shallow) and return its OUTBOUND (external)
    links only — the camps it recommends. Does not traverse the guide's own
    internal navigation."""
    browser_config = _browser_config()
    run_config = _run_config()
    guide_domain = _registered_domain(start_url)
    outbound: list[dict] = []
    seen: set[str] = set()

    async with _playwright_sem():
        async with AsyncWebCrawler(config=browser_config) as crawler:
            if not _is_allowed(start_url):
                from src import harvest_log

                harvest_log.robots_disallow(start_url)
                return []
            await asyncio.sleep(SETTINGS["delay_seconds"])
            try:
                result = await crawler.arun(url=start_url, config=run_config)
            except Exception as exc:
                logger.warning("Failed to crawl guide %s: %s", start_url, exc)
                return []

            for link in _extract_links_from_result(start_url, result):
                child = normalize_url(link["url"])
                if not child or child in seen:
                    continue
                if _registered_domain(child) == guide_domain:
                    continue  # internal — skip
                seen.add(child)
                outbound.append({"url": child, "text": link.get("text", "")})

    return outbound


async def walk_site(
    start_url: str,
    max_depth: int,
    max_pages: int,
    *,
    focused: bool = False,
    delay_seconds: float | None = None,
    stop_on_catalog: bool = False,
    link_gate=None,
) -> WalkResult:
    """Crawl a site collecting links.

    Default (focused=False) behaves like the original breadth-first walk.

    Focused mode (focused=True) is for rec-center / camp-host seeds:
      - Visits links in PRIORITY order (registration catalogs first, junk skipped).
      - Follows registration platforms (WebTrac/MyRec) off-domain.
      - Optionally stops as soon as a camp catalog (type=CAMP) is found.
      - `link_gate(url, text) -> bool` lets an LLM veto ambiguous links.
    """
    visited: set[str] = set()
    all_links: list[dict] = []
    page_text_by_url: dict[str, str] = {}
    delay = SETTINGS["delay_seconds"] if delay_seconds is None else delay_seconds

    # Priority queue: (-score, counter, url, depth, text, score).
    # Higher score visited first. Text/score kept so the optional LLM gate can
    # be applied lazily at POP time (after priority ordering) instead of during
    # enqueue — so the top-priority catalog is fetched before any slow LLM call.
    counter = itertools.count()
    queue: list[tuple[int, int, str, int, str, int]] = []

    def _push(url: str, depth: int, score: int, text: str = "") -> None:
        heapq.heappush(queue, (-score, next(counter), url, depth, text, score))

    _push(start_url, 0, 1000)  # always crawl the seed first

    from src import session_log

    mode = "focused" if focused else "breadth"
    session_log.trace_crawl_start(
        start_url=start_url,
        max_pages=max_pages,
        max_depth=max_depth,
        mode=mode,
    )

    browser_config = _browser_config()
    run_config = _run_config()

    async with _playwright_sem():
        async with AsyncWebCrawler(config=browser_config) as crawler:
            while queue and len(visited) < max_pages:
                _, _, url, depth, link_text, link_score = heapq.heappop(queue)
                normalized = normalize_url(url)
                if not normalized or normalized in visited:
                    if normalized:
                        session_log.trace_crawl_skip(url=normalized, reason="already visited")
                    continue
                if depth > max_depth:
                    session_log.trace_crawl_skip(url=normalized, reason=f"depth {depth} > max {max_depth}")
                    continue
                if focused and link_gate is not None and 0 <= link_score <= 10:
                    try:
                        if not link_gate(normalized, link_text):
                            session_log.trace_crawl_skip(
                                url=normalized, reason="LLM link gate rejected"
                            )
                            continue
                    except Exception:
                        pass
                if not _is_allowed(normalized):
                    from src import harvest_log

                    harvest_log.robots_disallow(normalized, source_url=start_url)
                    session_log.trace_crawl_skip(url=normalized, reason="robots.txt disallowed")
                    continue

                session_log.trace_crawl_visit(
                    n=len(visited) + 1,
                    max_pages=max_pages,
                    url=normalized,
                    depth=depth,
                    score=link_score,
                    link_text=link_text,
                )

                domain = _registered_domain(normalized)
                sem = _host_semaphores[domain]
                async with sem:
                    await asyncio.sleep(delay)
                    try:
                        result = await crawler.arun(url=normalized, config=run_config)
                    except Exception as exc:
                        logger.warning("Failed to crawl %s: %s", normalized, exc)
                        session_log.trace_crawl_skip(url=normalized, reason=f"fetch error: {exc}")
                        continue

                visited.add(normalized)
                text = _page_text_from_result(result)
                if text:
                    page_text_by_url[normalized] = text
                page_links = _extract_links_from_result(normalized, result)
                all_links.extend(page_links)
                session_log.trace_crawl_page_links(url=normalized, link_count=len(page_links))

                if focused and stop_on_catalog and is_camp_catalog_url(normalized):
                    session_log.trace_crawl_stop(url=normalized, reason="camp catalog URL found")
                    break

                if depth >= max_depth:
                    continue

                if not focused:
                    for link in page_links:
                        child = normalize_url(link["url"])
                        if not child or child in visited:
                            continue
                        if not _should_enqueue(start_url, child, depth, max_depth):
                            session_log.trace_crawl_skip(
                                url=child, reason="enqueue rules rejected"
                            )
                            continue
                        session_log.trace_crawl_enqueue(
                            url=child, depth=depth + 1, score=0, link_text=link.get("text", "")
                        )
                        _push(child, depth + 1, 0)
                    continue

                for link in page_links:
                    child = normalize_url(link["url"])
                    if not child or child in visited:
                        continue
                    if not _should_enqueue(start_url, child, depth, max_depth):
                        session_log.trace_crawl_skip(
                            url=child, reason="enqueue rules rejected"
                        )
                        continue
                    score = crawl_link_score(child, link.get("text", ""))
                    if score < 0:
                        session_log.trace_crawl_skip(url=child, reason="junk link (score < 0)")
                        continue
                    session_log.trace_crawl_enqueue(
                        url=child,
                        depth=depth + 1,
                        score=score,
                        link_text=link.get("text", ""),
                    )
                    _push(child, depth + 1, score, link.get("text", ""))

    return WalkResult(links=all_links, page_text_by_url=page_text_by_url)
