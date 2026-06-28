"""Agent-callable tools wrapping discover, validate, crawl, store, memory."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from config.settings import SETTINGS, STATE
from phase_c.agent_memory import load_memory, memory_summary, record_outcome
from shared.cache import get_cached_search_results, record_search
from phase_a.classify import classify
from phase_b.crawl import walk_site
from phase_a.discover import ConfigError, search
from phase_a.filter_links import is_likely_camp_link
from shared.llm import OllamaError, chat, resolve_model
from shared.store import count_camp_links, save_new_links
from shared.urls import normalize_url
from phase_a.validate_search_result import validate_search_results

from config.prompts import JUDGE_SEARCH_RESULTS_SYSTEM, REFLECTOR_SYSTEM

logger = logging.getLogger(__name__)


def tool_get_status() -> dict[str, Any]:
    return {
        "camp_links": count_camp_links(),
        "target": SETTINGS["target_count"],
        "memory": memory_summary(),
    }


def tool_list_uncrawled_candidates(limit: int = 10) -> list[dict]:
    from orchestrator.run import _load_candidates

    rows = _load_candidates()
    pending = [
        r
        for r in rows
        if r.get("crawled", "false") == "false"
        and r.get("classified_as") in ("directory", "unknown")
    ]
    pending.sort(key=lambda r: (r.get("preferred") != "true", r.get("url", "")))
    return pending[:limit]


def _llm_judge_results(query: str, items: list[dict]) -> list[dict]:
    if not items:
        return []
    payload = {
        "query": query,
        "results": [
            {"url": i["url"], "title": i.get("title", ""), "snippet": i.get("snippet", "")}
            for i in items
        ],
    }
    try:
        import json

        fast_model = resolve_model(SETTINGS.get("ollama_fast_model"))
        response = chat(
            JUDGE_SEARCH_RESULTS_SYSTEM,
            json.dumps(payload),
            model=fast_model,
            timeout=30,
            num_predict=128,
        )
        verdicts = {v["url"]: v for v in response.get("results", [])}
        kept = []
        for item in items:
            v = verdicts.get(item["url"], {})
            if v.get("verdict") == "keep":
                item = dict(item)
                item["source_type"] = v.get("type", item.get("source_type", "unknown"))
                kept.append(item)
        return kept
    except (OllamaError, KeyError, TypeError, ValueError) as exc:
        logger.warning("LLM judge failed, using rule validation only: %s", exc)
        return items


def tool_search(query: str, town: str, keyword: str, *, use_llm_judge: bool = True) -> dict:
    cached = get_cached_search_results(query)
    if cached is not None:
        raw = cached
    else:
        try:
            raw = search(query, SETTINGS["results_per_search"])
        except ConfigError:
            raise
        record_search(query, raw)
    kept, validation = validate_search_results(raw)

    if use_llm_judge and kept:
        unknown = [i for i in kept if i.get("source_type") == "unknown"]
        if unknown:
            judged = _llm_judge_results(query, unknown)
            preferred = [i for i in kept if i.get("source_type") != "unknown"]
            kept = preferred + judged

    rejected = [
        {
            "url": v.url,
            "reason": v.reason,
            "source_type": v.source_type,
        }
        for v in validation
        if v.verdict == "reject"
    ]

    return {
        "query": query,
        "town": town,
        "keyword": keyword,
        "skipped": False,
        "kept": kept,
        "rejected": rejected,
    }


def tool_save_candidates(rows: list[dict], phase: str = "A") -> int:
    from orchestrator.run import _append_candidates

    now = datetime.now(timezone.utc).isoformat()
    candidate_rows = []
    for item in rows:
        url = normalize_url(item["url"])
        if not url:
            continue
        candidate_rows.append(
            {
                "url": url,
                "state": STATE,
                "town": item.get("town", ""),
                "keyword": item.get("keyword", ""),
                "phase": phase,
                "classified_as": classify(url),
                "crawled": "false",
                "discovered_at": now,
                "title": item.get("title", ""),
                "preferred": "true" if item.get("preferred") else "false",
            }
        )
    if candidate_rows:
        _append_candidates(candidate_rows)
    return len(candidate_rows)


async def tool_crawl(url: str, town: str) -> dict:
    url = normalize_url(url)
    if not url:
        return {"url": url, "links_found": 0, "added": 0, "error": "invalid url"}

    try:
        walk = await walk_site(
            url,
            SETTINGS["max_crawl_depth"],
            SETTINGS["max_pages_per_source"],
        )
    except Exception as exc:
        return {"url": url, "links_found": 0, "added": 0, "error": str(exc)}

    rows = []
    for link in walk.links:
        if not is_likely_camp_link(link["url"], link.get("text", "")):
            continue
        rows.append(
            {
                "url": link["url"],
                "state": STATE,
                "town_hint": town,
                "source_type": "directory",
                "found_via": "agent",
                "found_on_page": url,
                "link_text": link.get("text", ""),
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    added = save_new_links(rows)
    return {"url": url, "links_found": len(rows), "added": added, "error": None}


def tool_reflect(action: str, context: dict, outcome: dict) -> dict:
    import json

    user = json.dumps({"action": action, "context": context, "outcome": outcome})
    try:
        reflection = chat(REFLECTOR_SYSTEM, user)
    except OllamaError as exc:
        reflection = {
            "success": outcome.get("added", 0) > 0 or len(outcome.get("kept", [])) > 0,
            "yield_score": min(1.0, (outcome.get("added", 0) or len(outcome.get("kept", []))) / 10),
            "lesson": str(exc),
            "next_suggestion": "",
        }

    record_outcome(
        action=action,
        query=context.get("query"),
        url=context.get("url") or outcome.get("url"),
        town=context.get("town"),
        success=bool(reflection.get("success")),
        yield_score=float(reflection.get("yield_score", 0)),
        lesson=str(reflection.get("lesson", "")),
        links_found=int(outcome.get("added", 0) or 0),
    )
    return reflection


def tool_memory_context() -> dict:
    return load_memory()
