"""Persistent agent memory across runs."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import tldextract

MEMORY_PATH = Path("cache/agent_memory.json")

DEFAULT_MEMORY: dict[str, Any] = {
    "query_scores": {},
    "domain_scores": {},
    "town_status": {},
    "lessons": [],
    "stats": {
        "total_searches": 0,
        "total_crawls": 0,
        "total_links_found": 0,
    },
}


def _registered_domain(url: str) -> str:
    parsed = urlparse(url)
    ext = tldextract.extract(parsed.netloc)
    if not ext.domain or not ext.suffix:
        return parsed.netloc.lower()
    return f"{ext.domain}.{ext.suffix}".lower()


def load_memory() -> dict[str, Any]:
    if not MEMORY_PATH.exists():
        return json.loads(json.dumps(DEFAULT_MEMORY))
    with open(MEMORY_PATH, encoding="utf-8") as f:
        data = json.load(f)
    for key, default in DEFAULT_MEMORY.items():
        data.setdefault(key, json.loads(json.dumps(default)))
    return data


def save_memory(data: dict[str, Any]) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def record_outcome(
    *,
    action: str,
    query: str | None = None,
    url: str | None = None,
    town: str | None = None,
    success: bool,
    yield_score: float,
    lesson: str,
    links_found: int = 0,
) -> None:
    mem = load_memory()
    mem["stats"]["total_searches"] += 1 if action == "search" else 0
    mem["stats"]["total_crawls"] += 1 if action == "crawl_page" else 0
    mem["stats"]["total_links_found"] += links_found

    if query:
        scores = mem["query_scores"]
        prev = scores.get(query, {"attempts": 0, "avg_yield": 0.0})
        attempts = prev["attempts"] + 1
        avg = (prev["avg_yield"] * prev["attempts"] + yield_score) / attempts
        scores[query] = {"attempts": attempts, "avg_yield": round(avg, 3), "last_success": success}

    if url:
        domain = _registered_domain(url)
        scores = mem["domain_scores"]
        prev = scores.get(domain, {"attempts": 0, "avg_yield": 0.0})
        attempts = prev["attempts"] + 1
        avg = (prev["avg_yield"] * prev["attempts"] + yield_score) / attempts
        scores[domain] = {"attempts": attempts, "avg_yield": round(avg, 3), "last_success": success}

    if town:
        town_data = mem["town_status"].setdefault(town, {"searches": 0, "links": 0})
        if action == "search":
            town_data["searches"] += 1
        town_data["links"] += links_found

    if lesson:
        mem["lessons"].append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "query": query,
                "url": url,
                "town": town,
                "success": success,
                "yield_score": yield_score,
                "lesson": lesson,
            }
        )
        mem["lessons"] = mem["lessons"][-200:]

    save_memory(mem)
    logging.info("Memory updated: %s", lesson[:120] if lesson else action)


def memory_summary() -> str:
    mem = load_memory()
    top_domains = sorted(
        mem["domain_scores"].items(),
        key=lambda x: x[1].get("avg_yield", 0),
        reverse=True,
    )[:5]
    recent_lessons = mem["lessons"][-5:]
    lines = [
        f"Total searches: {mem['stats']['total_searches']}, crawls: {mem['stats']['total_crawls']}, links: {mem['stats']['total_links_found']}",
    ]
    if top_domains:
        lines.append("Top domains: " + ", ".join(f"{d}({s['avg_yield']:.2f})" for d, s in top_domains))
    if recent_lessons:
        lines.append("Recent lessons:")
        for lesson in recent_lessons:
            lines.append(f"  - {lesson['lesson']}")
    return "\n".join(lines)
