"""Part C Stage 2 — session categorizer (rules first, Gemma batch second).

Quirky camp names ("Wizards & Wands", "Lexplorations: Tinker Lab") defeat
substring matching → false holes → wasted searches AND false coverage
confidence. Pipeline:

  1. rules (free): activity names + parent synonyms over name/url/platform
  2. Gemma batch pass (gemma3 fast model) for the remainder, 15 names/batch,
     multi-category output with confidence
  3. cache/session_categories.json keyed by normalized name+host — re-runs free

`categorize_sessions` annotates each session dict with `categories` (list) and
`category` (primary). parent_auditor consumes this; the substring path remains
the no-Ollama fallback.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from config.gap_taxonomy import ALL_CATEGORIES, PARENT_SYNONYMS, slugify
from config.settings import SETTINGS
from shared.llm import OllamaError, chat, is_available

logger = logging.getLogger(__name__)

import os as _os
_CACHE_PATH = Path(_os.environ.get("FIREFLY_CACHE_ROOT", "cache")) / "session_categories.json"

CATEGORIZER_SYSTEM = """You tag youth summer programs with activity categories.
Given a list of program names, return JSON only:
{"sessions":[{"name":"<name as given>","categories":["slug",...],"confidence":0.0-1.0}]}
Use ONLY slugs from this list (multiple allowed when a program spans several;
empty list if truly unknowable): %s
Examples: "Wizards & Wands" -> ["magic"]; "Tinker Lab" -> ["stem","maker"];
"Circus & Tumbling" -> ["circus_arts","gymnastics"]."""


def _rule_categories(blob: str) -> list[str]:
    """Free pass: activity display names + parent synonyms as substrings."""
    found: list[str] = []
    for slug, display in ALL_CATEGORIES.items():
        if display.lower() in blob:
            found.append(slug)
    for slug, syns in PARENT_SYNONYMS.items():
        if slug not in found and any(s in blob for s in syns):
            found.append(slug)
    # prefer specific over generic: drop bare "art"/"music" when a finer slug hit
    if len(found) > 1:
        generic = {"art", "music", "stem", "general_day_camp"}
        specific = [f for f in found if f not in generic]
        if specific:
            found = specific + [f for f in found if f in generic][:1]
    return found[:4]


def _cache_key(session: dict) -> str:
    name = re.sub(r"\s+", " ", (session.get("name") or "").strip().lower())
    host = urlparse(session.get("register_url") or session.get("info_url") or "").netloc
    return f"{host.lower().replace('www.', '')}|{name}"


def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache, indent=1))


def _gemma_batch(names: list[str]) -> dict[str, list[str]]:
    """One Gemma call for up to 15 names → {name: [slugs]}. Fail-open: {} on error."""
    slugs = ", ".join(sorted(ALL_CATEGORIES))
    try:
        resp = chat(
            CATEGORIZER_SYSTEM % slugs,
            json.dumps({"programs": names}, ensure_ascii=False),
            # 4b, not the 1b fast model: 1b truncates batch output (returned
            # 1 of 4 names in the Stage-2 acceptance run).
            model=SETTINGS.get("ollama_filter_model") or SETTINGS.get("ollama_model"),
            temperature=0.0,
            timeout=int(SETTINGS.get("ollama_session_timeout_s", 60)),
            num_predict=1024,
            purpose="session_categorizer",
        )
    except OllamaError as exc:
        logger.warning("categorizer batch failed (%d names): %s", len(names), exc)
        return {}
    out: dict[str, list[str]] = {}
    for item in resp.get("sessions", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        cats = [slugify(str(c)) for c in (item.get("categories") or []) if c]
        cats = [c for c in cats if c in ALL_CATEGORIES]
        if name:
            out[name] = cats[:4]
    return out


def categorize_sessions(sessions: list[dict], *, use_llm: bool = True) -> list[dict]:
    """Annotate sessions with categories (list) + category (primary). Mutates copies."""
    cache = _load_cache()
    out: list[dict] = []
    pending: list[dict] = []

    for s in sessions:
        s = dict(s)
        key = _cache_key(s)
        if key in cache:
            s["categories"] = cache[key]
        else:
            blob = " ".join(
                str(s.get(k) or "").lower()
                for k in ("name", "platform", "register_url", "info_url")
            )
            cats = _rule_categories(blob)
            if cats:
                s["categories"] = cats
                cache[key] = cats
            else:
                pending.append(s)
        out.append(s)

    if pending and use_llm and is_available():
        # smaller batches keep gemma3:4b complete (1b/large batches truncate)
        names_done: set[str] = set()
        uniq = list({p.get("name", ""): None for p in pending})
        for i in range(0, len(uniq), 8):
            verdicts = _gemma_batch(uniq[i : i + 8])
            for p in pending:
                name = p.get("name", "")
                if name in verdicts and name not in names_done:
                    p["categories"] = verdicts[name]
                    cache[_cache_key(p)] = verdicts[name]
            names_done.update(verdicts)
    for p in pending:
        p.setdefault("categories", [])

    for s in out:
        s["category"] = (s.get("categories") or [None])[0]
    _save_cache(cache)
    return out


def coverage_by_category(sessions: list[dict]) -> dict[str, list[dict]]:
    """category slug → sessions (a session counts toward every tag it holds)."""
    cov: dict[str, list[dict]] = {}
    for s in sessions:
        for c in s.get("categories") or []:
            cov.setdefault(c, []).append(s)
    return cov
