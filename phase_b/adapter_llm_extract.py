"""Task 3.1 — last-resort LLM program extraction (Gemma via Ollama).

Called only when structured + sawyer + rendered extraction all returned 0 for
a provider. Reads the seed page plus up to 2 same-host camp/register links,
asks the verify model to enumerate youth summer programs, and gates each
program on confidence and a same-host/registration-platform register URL.

Hosts that still yield 0 are appended to data/shared/firecrawl_queue.csv so a
later Firecrawl pass can pick them up.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from config.prompts import LLM_EXTRACT_SYSTEM
from config.settings import SETTINGS

logger = logging.getLogger(__name__)

# Monkeypatchable in tests.
CACHE_PATH = Path("cache/llm_extract.json")
FIRECRAWL_QUEUE_PATH = Path("data/shared/firecrawl_queue.csv")
FIRECRAWL_QUEUE_COLUMNS = ["host", "seed_url", "town", "reason"]

_FOLLOW_LINK_TEXT_RE = re.compile(r"(?i)(camp|summer|register|schedule|program|enroll)")


def _host(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _cache_key(host: str, page_text: str) -> str:
    return hashlib.sha256((host + (page_text or "")).encode("utf-8")).hexdigest()[:16]


def _load_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — cache is best-effort
        logger.warning("llm_extract cache unreadable: %s", exc)
    return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_extract cache write failed: %s", exc)


def queue_for_firecrawl(host: str, seed_url: str, town: str, reason: str) -> bool:
    """Append a still-failing host to the Firecrawl queue (dedupe on host)."""
    if not host:
        return False
    existing: set[str] = set()
    if FIRECRAWL_QUEUE_PATH.exists():
        with open(FIRECRAWL_QUEUE_PATH, encoding="utf-8", newline="") as f:
            existing = {row.get("host", "") for row in csv.DictReader(f)}
    if host in existing:
        return False
    FIRECRAWL_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not FIRECRAWL_QUEUE_PATH.exists()
    with open(FIRECRAWL_QUEUE_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIRECRAWL_QUEUE_COLUMNS)
        if new_file:
            w.writeheader()
        w.writerow({"host": host, "seed_url": seed_url, "town": town, "reason": reason})
    return True


def _extract_one(item: tuple) -> list[dict]:
    """One LLM call for one page; returns the raw programs list."""
    page_url, page_text, town = item
    from shared.llm import OllamaError, chat

    system = LLM_EXTRACT_SYSTEM.replace("<TOWN>", town or "this town")
    user = json.dumps(
        {"page_url": page_url, "page_text": page_text},
        ensure_ascii=False,
    )
    try:
        out = chat(
            system,
            user,
            model=SETTINGS.get("ollama_verify_model") or SETTINGS.get("ollama_model"),
            temperature=0.0,
            timeout=int(SETTINGS.get("ollama_session_timeout_s", 60)),
            purpose="llm_extract",
        )
    except OllamaError as exc:
        logger.warning("llm_extract failed for %s: %s", page_url, exc)
        return []
    programs = out.get("programs")
    return programs if isinstance(programs, list) else []


def _accept_program(prog: dict, seed_host: str) -> bool:
    from phase_b.registration import is_registration_platform_url

    try:
        confidence = float(prog.get("confidence", 0))
    except (TypeError, ValueError):
        return False
    if confidence < float(SETTINGS.get("llm_extract_min_confidence", 0.6)):
        return False
    reg = (prog.get("register_url") or "").strip()
    if not reg or not (prog.get("name") or "").strip():
        return False
    return _host(reg) == seed_host or is_registration_platform_url(reg)


def _to_session(prog: dict, seed_url: str) -> dict:
    from phase_b.platforms import make_session

    dates = str(prog.get("dates") or "")
    granularity = "program"
    try:
        from phase_c.deliverables import parse_date_range

        if parse_date_range(dates, int(SETTINGS.get("season_year", 2026))):
            granularity = "session"
    except Exception:  # noqa: BLE001 — date parse never blocks a row
        pass
    return make_session(
        str(prog.get("name") or ""),
        str(prog.get("register_url") or ""),
        platform="llm_extract",
        dates=dates,
        ages=str(prog.get("ages") or ""),
        price=str(prog.get("price") or ""),
        source_url=seed_url,
        kind="session",
        name_source="llm",
        granularity=granularity,
    )


async def extract_programs_llm(url: str, *, town: str) -> list[dict]:
    """LLM-extract programs from a custom provider site. Last-resort adapter."""
    from shared.llm import is_available
    from shared.llm_pool import run_batch

    host = _host(url)
    if not is_available():
        queue_for_firecrawl(host, url, town, "ollama_unavailable")
        return []

    from phase_b.platforms import _fetch

    max_chars = int(SETTINGS.get("ollama_session_max_chars", 6000))
    seed_text, seed_links = await _fetch(url, caller="llm_extract:seed")

    follow: list[str] = []
    for l in seed_links:
        u = l.get("url", "")
        if len(follow) >= 2:
            break
        if not u or _host(u) != host:
            continue
        if u.rstrip("/") == url.rstrip("/") or u in follow:
            continue
        if _FOLLOW_LINK_TEXT_RE.search(l.get("text", "") or ""):
            follow.append(u)

    pages: list[tuple[str, str]] = [(url, (seed_text or "")[:max_chars])]
    for u in follow:
        text, _ = await _fetch(u, caller="llm_extract:follow")
        if text:
            pages.append((u, text[:max_chars]))
    pages = [(u, t) for u, t in pages if t.strip()]
    if not pages:
        queue_for_firecrawl(host, url, town, "no_page_text")
        return []

    cache = _load_cache()
    cached_programs: list[dict] = []
    misses: list[tuple] = []
    miss_keys: list[str] = []
    for page_url, text in pages:
        key = _cache_key(host, text)
        if key in cache:
            cached_programs.extend(cache[key])
        else:
            misses.append((page_url, text, town))
            miss_keys.append(key)

    fresh_lists: list[list[dict]] = []
    if misses:
        fresh_lists = await run_batch(
            misses,
            _extract_one,
            concurrency=int(SETTINGS.get("ollama_verify_concurrency", 2)),
        )
        for key, programs in zip(miss_keys, fresh_lists):
            cache[key] = programs or []
        _save_cache(cache)

    all_programs = cached_programs + [p for lst in fresh_lists for p in (lst or [])]
    accepted = [p for p in all_programs if _accept_program(p, host)]

    if not accepted:
        reason = "llm_rejected_all" if all_programs else "llm_no_programs"
        queue_for_firecrawl(host, url, town, reason)
        return []

    sessions: list[dict] = []
    seen: set[str] = set()
    for prog in accepted:
        row = _to_session(prog, url)
        key = row.get("register_url", "")
        if key in seen:
            continue
        seen.add(key)
        sessions.append(row)
    return sessions
