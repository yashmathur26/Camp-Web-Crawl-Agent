"""Plain fetch path (task 2.2, R5). The ONE non-rendered way to fetch a page.

- httpx, configured UA, robots.txt respected, per-host politeness delay
- timeout from config; retry ×1 on CONNECTION error only — never on timeout
  (the old pipeline's 3× timeout retries tripled every hang)
- media-class URLs refused before any network I/O (R5.5)
- per-provider wall-clock Budget object (R5.4)
- every fetch logged with ms + chars (R7.4 narration feeds off this)
"""

from __future__ import annotations

import logging
import re
import time
from html import unescape
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from config_engine import ENGINE
from engine.fetch.cache import FetchCache
from engine.fetch.urls import is_media_url, to_absolute
from engine.model import FetchRecord

logger = logging.getLogger("engine.fetch")

_TAG_RE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", re.I)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_A_RE = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>', re.I)


class BudgetExceeded(Exception):
    pass


class Budget:
    """Wall-clock budget per provider (R5.4). Check between fetches."""

    def __init__(self, seconds: float | None = None):
        self.seconds = float(seconds if seconds is not None else ENGINE["provider_budget_s"])
        self.started = time.monotonic()

    def remaining(self) -> float:
        return self.seconds - (time.monotonic() - self.started)

    def check(self) -> None:
        if self.remaining() <= 0:
            raise BudgetExceeded(f"provider budget of {self.seconds:.0f}s exhausted")


def html_to_text(html: str) -> str:
    body = _TAG_RE.sub(" ", html or "")
    text = _HTML_TAG_RE.sub(" ", body)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def extract_links(base_url: str, html: str) -> list[dict]:
    links = []
    for m in _A_RE.finditer(html or ""):
        # hrefs in rendered DOM serialization carry entity-encoded ampersands
        # (&amp;FMID=...) which break query parsing downstream — unescape first.
        url = to_absolute(base_url, unescape(m.group(1)))
        if not url:
            continue
        text = re.sub(r"\s+", " ", _HTML_TAG_RE.sub(" ", m.group(2))).strip()
        links.append({"url": url, "text": unescape(text)})
    return links


class FetchClient:
    """Shared by all extractors. Holds the run cache, robots state, politeness
    clocks, and the fetch log."""

    def __init__(self, cache: FetchCache | None = None):
        self.cache = cache or FetchCache()
        self.log: list[FetchRecord] = []
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": ENGINE["user_agent"]},
            timeout=float(ENGINE["fetch_timeout_s"]),
            follow_redirects=True,
        )

    # -- internals ---------------------------------------------------------

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        scheme = parsed.scheme or "https"
        if host not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self._client.get(f"{scheme}://{host}/robots.txt")
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._robots[host] = rp
                else:
                    self._robots[host] = None
            except httpx.HTTPError:
                self._robots[host] = None
        rp = self._robots[host]
        return rp is None or rp.can_fetch(ENGINE["user_agent"], url)

    def _politeness(self, url: str) -> None:
        host = urlparse(url).netloc.lower()
        delay = float(ENGINE["politeness_delay_s"])
        elapsed = time.monotonic() - self._last_hit.get(host, 0.0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_hit[host] = time.monotonic()

    def _record(self, url: str, status: str, ms: int, chars: int, note: str = "") -> None:
        self.log.append(FetchRecord(url=url, status=status, ms=ms, chars=chars, note=note))
        logger.info("fetch %-7s %5dms %7d chars  %s %s", status, ms, chars, url, note)

    # -- public ------------------------------------------------------------

    def fetch_text(
        self, url: str, *, budget: Budget | None = None
    ) -> tuple[str, list[dict], str]:
        """Return (text, links, raw_html). Empty text on refusal/error — the
        caller diagnoses a Gap; this layer never raises except BudgetExceeded."""
        if budget is not None:
            budget.check()
        if is_media_url(url):
            self._record(url, "refused", 0, 0, "media-class url")
            return "", [], ""
        cached = self.cache.get(url)
        if cached is not None:
            text, links, _status = cached
            self._record(url, "cache", 0, len(text))
            return text, links, ""
        if not self._allowed(url):
            self._record(url, "refused", 0, 0, "robots.txt")
            return "", [], ""

        self._politeness(url)
        t0 = time.monotonic()
        for attempt in (1, 2):
            try:
                resp = self._client.get(url)
                html = resp.text or ""
                text = html_to_text(html)
                links = extract_links(str(resp.url), html)
                ms = int((time.monotonic() - t0) * 1000)
                self._record(url, "ok", ms, len(text), f"http={resp.status_code}")
                if resp.status_code < 400:
                    self.cache.put(url, text, links, resp.status_code)
                    return text, links, html
                return "", links, html  # 4xx/5xx: no cache, caller diagnoses
            except httpx.TimeoutException as exc:
                # R5.2: timeouts are NEVER retried.
                ms = int((time.monotonic() - t0) * 1000)
                self._record(url, "error", ms, 0, f"timeout: {exc}")
                return "", [], ""
            except httpx.HTTPError as exc:
                if attempt == 2:
                    ms = int((time.monotonic() - t0) * 1000)
                    self._record(url, "error", ms, 0, f"connection: {exc}")
                    return "", [], ""
                time.sleep(0.5)  # retry ×1 on connection error only
        return "", [], ""

    def fetch_json(self, url: str, *, budget: Budget | None = None):
        """Vendor data path helper (R5.7): GET a JSON endpoint, raw body —
        never through html_to_text (entity unescaping would corrupt payloads).
        Returns parsed JSON or None. Cached via the same normalized-URL cache."""
        import json as json_mod

        if budget is not None:
            budget.check()
        cached = self.cache.get(url)
        if cached is not None:
            self._record(url, "cache", 0, len(cached[0]))
            try:
                return json_mod.loads(cached[0])
            except json_mod.JSONDecodeError:
                return None
        if not self._allowed(url):
            self._record(url, "refused", 0, 0, "robots.txt")
            return None
        self._politeness(url)
        t0 = time.monotonic()
        try:
            resp = self._client.get(url, headers={"Accept": "application/json"})
            ms = int((time.monotonic() - t0) * 1000)
            body = resp.text or ""
            self._record(url, "ok", ms, len(body), f"http={resp.status_code} (json)")
            if resp.status_code >= 400:
                return None
            data = json_mod.loads(body)
            self.cache.put(url, body, [], resp.status_code)
            return data
        except (httpx.HTTPError, json_mod.JSONDecodeError) as exc:
            ms = int((time.monotonic() - t0) * 1000)
            self._record(url, "error", ms, 0, f"json: {exc}")
            return None

    def close(self) -> None:
        self._client.close()
        self.cache.close()
