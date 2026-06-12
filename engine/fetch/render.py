"""Rendered fetch path (task 2.3, R5.2). The ONE Playwright path.

- domcontentloaded + DOM-settle poll (stable for `settle_stable_s`), NEVER
  networkidle (it hung 6m43s on a 171-char MyRec shell)
- hard wall cap (default 20s), SINGLE attempt — timeouts are not retried
- browser pool capped at ENGINE["max_browsers"]
"""

from __future__ import annotations

import asyncio
import logging
import time

from config_engine import ENGINE
from engine.fetch.cache import FetchCache
from engine.fetch.client import extract_links, html_to_text
from engine.fetch.urls import is_media_url
from engine.model import FetchRecord

logger = logging.getLogger("engine.fetch.render")

_browser_sem: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    global _browser_sem
    if _browser_sem is None:
        _browser_sem = asyncio.Semaphore(int(ENGINE["max_browsers"]))
    return _browser_sem


async def fetch_rendered(
    url: str,
    *,
    cache: FetchCache | None = None,
    log: list[FetchRecord] | None = None,
    cap_s: float | None = None,
    settle_stable_s: float = 1.5,
    poll_s: float = 0.4,
) -> tuple[str, list[dict], str]:
    """Render `url`; return (text, links, html). Empty text on failure/cap —
    the caller diagnoses `render_failed`. One attempt, hard wall cap."""
    cap = float(cap_s if cap_s is not None else ENGINE["render_cap_s"])
    t0 = time.monotonic()

    def _record(status: str, chars: int, note: str = "") -> None:
        ms = int((time.monotonic() - t0) * 1000)
        rec = FetchRecord(url=url, status=status, ms=ms, chars=chars, note=note)
        if log is not None:
            log.append(rec)
        logger.info("render %-7s %5dms %7d chars  %s %s", status, ms, chars, url, note)

    if is_media_url(url):
        _record("refused", 0, "media-class url")
        return "", [], ""
    if cache is not None:
        cached = cache.get(url)
        if cached is not None:
            text, links, _status = cached
            _record("cache", len(text))
            return text, links, ""

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        _record("error", 0, "playwright not installed")
        return "", [], ""

    html = ""
    try:
        async with _sem():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(user_agent=ENGINE["user_agent"])
                    await page.goto(
                        url, wait_until="domcontentloaded",
                        timeout=int(cap * 1000),
                    )
                    # DOM-settle poll: body length stable for settle_stable_s,
                    # all inside the same hard cap.
                    last_len = -1
                    stable_since = time.monotonic()
                    while time.monotonic() - t0 < cap:
                        cur = await page.evaluate("document.body ? document.body.innerHTML.length : 0")
                        if cur != last_len:
                            last_len = cur
                            stable_since = time.monotonic()
                        elif time.monotonic() - stable_since >= settle_stable_s:
                            break
                        await asyncio.sleep(poll_s)
                    html = await page.content()
                finally:
                    await browser.close()
    except Exception as exc:  # noqa: BLE001 — single attempt; caller diagnoses
        _record("error", 0, f"{type(exc).__name__}: {exc}")
        return "", [], ""

    text = html_to_text(html)
    links = extract_links(url, html)
    _record("ok", len(text))
    if cache is not None and text.strip():
        cache.put(url, text, links)
    return text, links, html
