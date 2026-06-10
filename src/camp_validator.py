"""Ollama validation: is this page a youth summer camp / program parents can register for?"""

import asyncio
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from config.prompts import (
    CAMP_PAGE_CLASSIFIER_SYSTEM,
    CAMP_PAGE_FAST_CLASSIFIER_SYSTEM,
    CAMP_SESSION_EXTRACTOR_SYSTEM,
    LINK_FOLLOW_SYSTEM,
    YOUTH_SUMMER_TIEBREAK_SYSTEM,
)
from config.settings import SETTINGS
from src import harvest_log
from src.llm import OllamaError, chat, is_available
from src.registration import is_camp_catalog_url, is_registration_platform_url
from src.urls import normalize_url

logger = logging.getLogger(__name__)

_VERDICT_CACHE_PATH = Path("cache/camp_verdicts.json")

# Obvious camp registration URLs — skip LLM to save time.
# Do NOT match /class-category/ (use /class/(?!category)).
_HIGH_CONFIDENCE_RE = re.compile(
    r"program_details\.aspx|"
    r"myvscloud\.com|webtrac|"
    r"/camp[/\-]|summer-camp|summer-camps|specialty-camp|"
    r"lexplorations|/class/(?!category)[^/]+|"
    r"arux\.app/courses|"
    r"type=camp|module=ar|"
    r"/summervacation|summer_vacation|summerfun|"
    r"ymca.*/camp|/day-camp",
    re.IGNORECASE,
)

# Auto-DROP without LLM
_AUTO_DROP_RE = re.compile(
    r"\.pdf($|\?)|wp-content/uploads.*\.(jpg|jpeg|png|gif)|"
    r"\.gov/documentcenter|/senior(/|$)|/membership(/|$)|"
    r"/government/|/discover/contact|"
    r"mail\.google\.com|printfriendly\.com|gmail\.com/mail",
    re.IGNORECASE,
)

# Always run LLM when heuristic match is likely a false positive.
_LLM_REQUIRED_RE = re.compile(
    r"\.gov/|documentcenter|calendar\.aspx|formcenter|"
    r"senior|tax|vaccine|parking|housing|liheap|"
    r"crime|jail|storm-water|rain-barrel|classification",
    re.IGNORECASE,
)


def _load_verdict_cache() -> dict[str, dict]:
    if not _VERDICT_CACHE_PATH.exists():
        return {}
    try:
        with open(_VERDICT_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_verdict_cache(cache: dict[str, dict]) -> None:
    _VERDICT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_VERDICT_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def should_auto_drop(url: str) -> tuple[bool, str]:
    if _AUTO_DROP_RE.search(url):
        return True, "auto-drop (PDF/media/membership/senior)"
    return False, ""


def should_skip_llm(url: str) -> bool:
    """High-confidence camp URLs do not need a model call."""
    if should_auto_drop(url)[0]:
        return False
    return bool(_HIGH_CONFIDENCE_RE.search(url))


def make_link_follow_gate():
    """Return a sync `gate(url, text) -> bool` deciding if an ambiguous link is
    'worth pressing' during a focused crawl. Caps model calls per source and
    fails open (follow) so a slow/unavailable model never blocks discovery."""
    if not SETTINGS.get("ollama_link_follow"):
        return None
    if not is_available():
        logger.info("Ollama unavailable — link-follow gate disabled (rules only)")
        return None

    budget = {"left": int(SETTINGS.get("ollama_link_follow_max_per_source", 6))}
    cache: dict[str, bool] = {}
    model = SETTINGS.get("ollama_filter_model") or SETTINGS["ollama_model"]

    def gate(url: str, text: str = "") -> bool:
        # Always follow registration platforms; never spend budget on them.
        if is_registration_platform_url(url):
            return True
        norm = normalize_url(url)
        if norm in cache:
            return cache[norm]
        if budget["left"] <= 0:
            return True  # out of budget — don't block, let rules decide downstream
        budget["left"] -= 1
        user = json.dumps({"url": url, "link_text": text}, ensure_ascii=False)
        try:
            resp = chat(
                LINK_FOLLOW_SYSTEM,
                user,
                model=model,
                temperature=0.0,
                timeout=SETTINGS.get("ollama_link_follow_timeout_s", 20),
                purpose="link_follow_gate",
            )
            follow = bool(resp.get("follow"))
        except OllamaError as exc:
            logger.warning("Link-follow gate failed for %s: %s — following", url, exc)
            return True
        cache[norm] = follow
        harvest_log.link_follow_decision(url=url, follow=follow)
        return follow

    return gate


def should_require_llm(url: str) -> bool:
    """Low-confidence URLs (town gov noise) should always be checked."""
    if _LLM_REQUIRED_RE.search(url):
        return True
    host = urlparse(url).netloc.lower()
    return host.endswith(".gov")


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def classify_camp_page_tiered(
    url: str,
    *,
    link_text: str = "",
    town_hint: str = "",
    page_text: str = "",
) -> tuple[bool, str, str]:
    """Two-model classify: fast first, verifier on low confidence. Returns (is_camp, reason, stage)."""
    user = json.dumps(
        {
            "url": url,
            "link_text": link_text,
            "town_hint": town_hint,
            "page_text": _truncate(page_text, SETTINGS["ollama_validate_max_chars"]),
        },
        ensure_ascii=False,
    )
    fast_model = SETTINGS.get("ollama_fast_model") or SETTINGS.get("ollama_filter_model")
    verify_model = SETTINGS.get("ollama_verify_model") or SETTINGS["ollama_model"]

    fast_resp = chat(
        CAMP_PAGE_FAST_CLASSIFIER_SYSTEM,
        user,
        model=fast_model,
        temperature=0.0,
        timeout=min(SETTINGS["ollama_validate_timeout_s"], 20),
        num_predict=64,
        purpose="classify_camp_fast",
    )
    is_camp = bool(fast_resp.get("is_camp"))
    confidence = str(fast_resp.get("confidence", "low")).lower()
    reason = str(fast_resp.get("reason", ""))

    if confidence == "high":
        return is_camp, reason, "fast"

    verify_resp = chat(
        CAMP_PAGE_CLASSIFIER_SYSTEM,
        user,
        model=verify_model,
        temperature=0.0,
        timeout=SETTINGS["ollama_validate_timeout_s"],
        num_predict=64,
        purpose="classify_camp_verify",
    )
    v_is_camp = bool(verify_resp.get("is_camp"))
    v_reason = str(verify_resp.get("reason", reason))
    if confidence == "low" and is_camp != v_is_camp:
        return False, f"disagreement fast={is_camp} verify={v_is_camp}: {v_reason}", "verify-drop"
    return v_is_camp, v_reason, "verify"


def classify_camp_page(
    url: str,
    *,
    link_text: str = "",
    town_hint: str = "",
    page_text: str = "",
) -> tuple[bool, str]:
    """Return (is_camp, reason). Uses Ollama JSON mode."""
    user = json.dumps(
        {
            "url": url,
            "link_text": link_text,
            "town_hint": town_hint,
            "page_text": _truncate(page_text, SETTINGS["ollama_validate_max_chars"]),
        },
        ensure_ascii=False,
    )
    model = SETTINGS.get("ollama_filter_model") or SETTINGS["ollama_model"]
    response = chat(
        CAMP_PAGE_CLASSIFIER_SYSTEM,
        user,
        model=model,
        temperature=0.0,
        timeout=SETTINGS["ollama_validate_timeout_s"],
        num_predict=64,
        purpose="classify_camp_page",
    )
    is_camp = bool(response.get("is_camp"))
    reason = str(response.get("reason", ""))
    return is_camp, reason


def verify_youth_summer(
    name: str,
    *,
    ages: str = "",
    dates: str = "",
    text: str = "",
    town_hint: str = "",
) -> tuple[bool, str]:
    """LLM tie-breaker: is this session a youth SUMMER camp/clinic/workshop?

    Returns (keep, reason). Used only for ambiguous heuristic drops."""
    user = json.dumps(
        {
            "name": name,
            "ages": ages,
            "dates": dates,
            "text": _truncate(text, 500),
            "town_hint": town_hint,
        },
        ensure_ascii=False,
    )
    model = SETTINGS.get("ollama_filter_model") or SETTINGS["ollama_model"]
    response = chat(
        YOUTH_SUMMER_TIEBREAK_SYSTEM,
        user,
        model=model,
        temperature=0.0,
        timeout=SETTINGS.get("ollama_focus_verify_timeout_s", 20),
        num_predict=48,
        purpose="youth_summer_tiebreak",
    )
    keep = bool(response.get("keep"))
    reason = str(response.get("reason", ""))
    return keep, reason


_STOPWORDS = {"camp", "camps", "the", "and", "for", "a", "of", "program", "programs", "summer"}


def _name_tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOPWORDS}


def attach_session_links(
    sessions: list[dict], page_links: list[dict], *, max_per: int = 3
) -> list[dict]:
    """Match each extracted camp to the page's hyperlinks (by link text) and
    attach register_urls. Prefers registration/catalog links."""
    for s in sessions:
        name = s.get("name", "")
        name_l = name.lower().strip()
        name_tok = _name_tokens(name)
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for link in page_links:
            ltext = (link.get("text") or "").strip()
            url = normalize_url(link.get("url", ""))
            if not url or url in seen:
                continue
            lt_l = ltext.lower()
            score = 0
            if lt_l and (lt_l == name_l or name_l in lt_l or lt_l in name_l):
                score = 100
            else:
                overlap = name_tok & _name_tokens(ltext)
                if overlap:
                    score = 10 * len(overlap)
            if score <= 0:
                continue
            if is_camp_catalog_url(url):
                score += 5
            elif is_registration_platform_url(url):
                score += 3
            seen.add(url)
            scored.append((score, url))
        scored.sort(key=lambda x: x[0], reverse=True)
        s["register_urls"] = [u for _, u in scored[:max_per]]
    return sessions


_DATE_RANGE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
_DATE_ONLY_RE = re.compile(r"^[\d/\s\-–]+$")


def extract_webtrac_search_results(page_links: list[dict], page_text: str = "") -> list[dict]:
    """Parse WebTrac YMCA search-result rows when iteminfo links aren't present."""
    sessions = extract_registration_sessions(page_links)
    if sessions:
        return sessions
    # Fallback: week rows in link text like "Week 2: Sports Mania"
    week_re = re.compile(r"week\s*\d+[:\s-]+(.+)", re.I)
    out: list[dict] = []
    seen: set[str] = set()
    for link in page_links:
        text = (link.get("text") or "").strip()
        url = normalize_url(link.get("url", ""))
        if not text or not url or url in seen:
            continue
        m = week_re.search(text)
        if not m:
            continue
        seen.add(url)
        out.append({"name": text, "dates": "", "register_url": url, "id": url})
    return out


def extract_registration_sessions(page_links: list[dict]) -> list[dict]:
    """Parse a WebTrac/myvscloud catalog page's links into individual camp
    sessions. Each session is a unique item (FMID) with its own register link.

    Returns [{name, dates, register_url, id}]. Catalog text is usually pruned to
    nothing, so we read the link structure instead of asking the LLM."""
    from urllib.parse import parse_qs, urlparse

    by_id: dict[str, dict] = {}
    for link in page_links:
        url = link.get("url", "")
        text = (link.get("text") or "").strip()
        parsed = urlparse(url)
        if "iteminfo" not in parsed.path.lower():
            continue
        qs = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
        fmid = (qs.get("fmid") or [""])[0]
        if not fmid:
            continue
        entry = by_id.setdefault(fmid, {"name": "", "dates": "", "register_url": "", "id": fmid})
        low = url.lower()
        is_secondary = any(x in low for x in ("option=", "mode=", "interfaceparameter"))
        if not is_secondary:
            # canonical item link: text is the camp name, url is where to register
            if text and not _DATE_ONLY_RE.match(text):
                entry["name"] = entry["name"] or text
            entry["register_url"] = entry["register_url"] or normalize_url(url)
        if _DATE_RANGE_RE.search(text):
            entry["dates"] = entry["dates"] or text
    sessions = [e for e in by_id.values() if e["register_url"]]
    return sessions


def extract_camp_sessions(
    url: str,
    *,
    page_text: str = "",
    page_links: list[dict] | None = None,
    town_hint: str = "",
) -> list[dict]:
    """Enumerate the individual youth summer camps/sessions listed on a camp page.

    Returns a list of {name, type, ages, dates, register_urls}. Empty list if
    none found or the model is unavailable. When `page_links` is given, each camp
    is matched to its registration link(s) on the page."""
    if not page_text.strip():
        return []
    from src import session_log

    truncated = _truncate(page_text, SETTINGS["ollama_session_max_chars"])
    user = json.dumps(
        {
            "url": url,
            "town_hint": town_hint,
            "page_text": truncated,
        },
        ensure_ascii=False,
    )
    model = SETTINGS.get("ollama_verify_model") or SETTINGS.get("ollama_filter_model") or SETTINGS["ollama_model"]
    session_log.llm_extract_start(
        url=url,
        text_chars=len(truncated),
        link_count=len(page_links or []),
        model=model,
    )
    session_log.llm_extract_waiting(
        model=model,
        timeout_s=int(SETTINGS["ollama_session_timeout_s"]),
    )
    try:
        response = chat(
            CAMP_SESSION_EXTRACTOR_SYSTEM,
            user,
            model=model,
            temperature=0.0,
            timeout=SETTINGS["ollama_session_timeout_s"],
            num_predict=int(SETTINGS.get("ollama_session_num_predict", 2048)),
            purpose="camp_session_extract",
        )
    except OllamaError as exc:
        logger.warning("Camp-session extraction failed for %s: %s", url, exc)
        session_log.llm_extract_error(error=str(exc))
        return []
    camps = response.get("camps", [])
    if not isinstance(camps, list):
        session_log.llm_extract_error(error="model JSON had no 'camps' list")
        return []
    cleaned: list[dict] = []
    for c in camps:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        cleaned.append(
            {
                "name": name,
                "type": str(c.get("type", "")).strip(),
                "ages": str(c.get("ages", "")).strip(),
                "dates": str(c.get("dates", "")).strip(),
                "register_urls": [],
            }
        )
    session_log.llm_extract_raw_camps(camps=cleaned)
    if page_links:
        attach_session_links(cleaned, page_links)
        for s in cleaned:
            regs = s.get("register_urls") or []
            session_log.llm_extract_link_match(
                name=s.get("name", ""),
                register_url=regs[0] if regs else None,
            )
    return cleaned


def _cached_verdict(url: str, cache: dict[str, dict]) -> tuple[bool, str] | None:
    entry = cache.get(normalize_url(url))
    if not entry:
        return None
    return bool(entry.get("is_camp")), str(entry.get("reason", ""))


async def filter_rows_with_llm(
    rows: list[dict],
    page_text_by_url: dict[str, str],
    *,
    fetch_page_text,
) -> tuple[list[dict], int]:
    """Keep rows the model confirms are camp/program pages. Returns (kept, rejected_count)."""
    from src.llm_pool import get_metrics, reset_metrics, run_batch

    if not rows or not SETTINGS.get("ollama_validate_links"):
        return rows, 0
    if not is_available():
        logger.info("Ollama unavailable — skipping LLM camp validation")
        return rows, 0

    reset_metrics()
    metrics = get_metrics()
    cache = _load_verdict_cache()
    kept: list[dict] = []
    rejected = 0
    fetches = 0
    max_fetches = SETTINGS["ollama_validate_max_fetches_per_source"]
    max_llm_calls = int(SETTINGS.get("ollama_validate_max_calls_per_source") or 0)
    skipped_by_cap = 0

    pending: list[tuple[dict, str, str]] = []
    rule_kept = 0

    for row in rows:
        url = row.get("url", "")
        norm = normalize_url(url)
        if not norm:
            continue

        drop, drop_reason = should_auto_drop(url)
        if drop:
            rejected += 1
            metrics.skipped_rules += 1
            harvest_log.link_llm_verdict(url=url, kept=False, reason=drop_reason, cached=False)
            continue

        if should_skip_llm(url) and not should_require_llm(url):
            kept.append(row)
            rule_kept += 1
            metrics.skipped_rules += 1
            harvest_log.link_llm_verdict(
                url=url, kept=True, reason="high-confidence camp URL (rules)", cached=False
            )
            continue

        cached = _cached_verdict(url, cache)
        if cached is not None:
            metrics.cache_hits += 1
            if cached[0]:
                kept.append(row)
            else:
                rejected += 1
            harvest_log.link_llm_verdict(
                url=url, kept=cached[0], reason=cached[1], cached=True
            )
            continue

        if max_llm_calls and len(pending) + metrics.fast_calls + metrics.verify_calls >= max_llm_calls:
            skipped_by_cap += 1
            rejected += 1
            continue

        page_text = page_text_by_url.get(norm, "")
        if not page_text and fetches < max_fetches:
            logger.info(
                "LLM fetch %d/%d: %s",
                fetches + 1,
                min(max_fetches, len(rows) - rule_kept - rejected),
                url[:80],
            )
            try:
                page_text = await fetch_page_text(url)
                fetches += 1
            except Exception as exc:
                logger.warning("Could not fetch text for LLM validation %s: %s", url, exc)
        pending.append((row, url, page_text))

    if pending:
        est_sec = max(15, len(pending) * 3)
        logger.info(
            "LLM classify: %d link(s) (%d rule-kept, %d fetched) — ~%ds, log may be quiet",
            len(pending),
            rule_kept,
            fetches,
            est_sec,
        )

    use_tiered = bool(SETTINGS.get("ollama_fast_model"))

    def _classify(item):
        row, url, page_text = item
        try:
            if use_tiered:
                is_camp, reason, stage = classify_camp_page_tiered(
                    url,
                    link_text=row.get("link_text", ""),
                    town_hint=row.get("town_hint", ""),
                    page_text=page_text,
                )
                if stage == "fast":
                    metrics.fast_calls += 1
                else:
                    metrics.verify_calls += 1
            else:
                is_camp, reason = classify_camp_page(
                    url,
                    link_text=row.get("link_text", ""),
                    town_hint=row.get("town_hint", ""),
                    page_text=page_text,
                )
                metrics.fast_calls += 1
            return row, url, is_camp, reason
        except OllamaError as exc:
            logger.warning("LLM camp validation failed for %s: %s — keeping (rules only)", url, exc)
            return row, url, True, str(exc)

    if pending:
        results = await run_batch(
            pending,
            _classify,
            concurrency=int(SETTINGS.get("ollama_classify_concurrency", 3)),
        )
        for row, url, is_camp, reason in results:
            norm = normalize_url(url)
            cache[norm] = {"is_camp": is_camp, "reason": reason, "url": norm}
            harvest_log.link_llm_verdict(url=url, kept=is_camp, reason=reason, cached=False)
            if is_camp:
                kept.append(row)
            else:
                rejected += 1

    if cache:
        _save_verdict_cache(cache)
    if skipped_by_cap:
        harvest_log.llm_cap_reached(max_calls=max_llm_calls, skipped=skipped_by_cap)
    harvest_log.llm_funnel_metrics(**metrics.as_dict())
    return kept, rejected
