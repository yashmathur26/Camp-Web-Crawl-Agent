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
# P1.1: ONE shared Chromium for the whole process — each render opens a fresh
# PAGE (cheap), not a new browser (~300MB). The W3W crash churned a browser per
# render across 90+ MyRec details. shutdown_browser_pool() is called per town.
_playwright = None
_browser = None
_browser_loop = None  # the event loop the browser belongs to
_browser_lock: asyncio.Lock | None = None


def _sem() -> asyncio.Semaphore:
    global _browser_sem
    if _browser_sem is None:
        _browser_sem = asyncio.Semaphore(int(ENGINE["max_browsers"]))
    return _browser_sem


def _abandon_pool() -> None:
    """Drop refs WITHOUT awaiting close — used when the creating event loop is
    already dead (a Playwright object can't be closed from a different loop;
    awaiting it would hang). The orphaned subprocess is reaped at process exit."""
    global _playwright, _browser, _browser_loop
    _playwright = None
    _browser = None
    _browser_loop = None


async def _get_browser():
    """Lazily start one shared headless Chromium; reused across renders within
    one event loop. A Playwright browser is bound to the loop that created it,
    so on a new loop (a fresh asyncio.run) we abandon the old refs and rebuild —
    the per-process pool stays safe across run scopes without hanging."""
    global _playwright, _browser, _browser_loop, _browser_lock
    loop = asyncio.get_running_loop()
    # Loop changed → old browser + old lock belong to a dead loop; abandon both.
    if _browser_loop is not None and _browser_loop is not loop:
        _abandon_pool()
        _browser_lock = None
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    async with _browser_lock:
        if _browser is not None and not _browser.is_connected():
            await _close_pool()
        if _browser is None:
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
            _browser_loop = loop
            logger.info("started shared Chromium (browser pool)")
        return _browser


async def _close_pool() -> None:
    global _playwright, _browser, _browser_loop
    try:
        if _browser is not None:
            await _browser.close()
        if _playwright is not None:
            await _playwright.stop()
    except Exception as exc:  # noqa: BLE001
        logger.debug("browser pool close: %s", exc)
    finally:
        _browser = None
        _playwright = None
        _browser_loop = None


async def shutdown_browser_pool() -> None:
    """Close the shared browser + Playwright (call at town/loop boundaries).

    Only closes when called from the loop that created the browser; from a
    different loop it abandons the refs (closing cross-loop would hang)."""
    global _browser_loop
    if _browser is None:
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None and running is _browser_loop:
        await _close_pool()
    else:
        _abandon_pool()


def _atexit_shutdown() -> None:
    """Last-resort cleanup so a lingering Chromium subprocess never blocks
    process exit. The creating loop is gone by now, so kill the node subprocess
    directly rather than awaiting an unusable close()."""
    global _playwright, _browser
    proc = getattr(getattr(_playwright, "_connection", None), "_transport", None)
    child = getattr(proc, "_proc", None)
    if child is not None:
        try:
            child.kill()
        except Exception:  # noqa: BLE001
            pass
    _abandon_pool()


import atexit as _atexit

_atexit.register(_atexit_shutdown)


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
            text, links, _status, html = cached
            _record("cache", len(text))
            return text, links, html

    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        _record("error", 0, "playwright not installed")
        return "", [], ""

    html = ""
    try:
        async with _sem():
            browser = await _get_browser()
            page = await browser.new_page(user_agent=ENGINE["user_agent"])
            try:
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
                await page.close()  # close the PAGE, keep the shared browser
    except Exception as exc:  # noqa: BLE001 — single attempt; caller diagnoses
        _record("error", 0, f"{type(exc).__name__}: {exc}")
        return "", [], ""

    text = html_to_text(html)
    links = extract_links(url, html)
    _record("ok", len(text))
    if cache is not None and text.strip():
        cache.put(url, text, links, html=html)
    return text, links, html
