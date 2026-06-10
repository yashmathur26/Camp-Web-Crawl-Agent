"""Phase C gap-fill: targeted searches for missing camp categories."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from config.gap_taxonomy import GAP_CATEGORIES, GAP_SEARCH_TEMPLATES
from config.settings import SETTINGS, STATE
from src.data_layout import camp_links_csv, quality_tier_csv
from src.discover import ConfigError, search
from src.llm import OllamaError, chat, is_available
from src.session_quality import split_sessions
from src.store import save_new_links
from src.urls import normalize_url
from src.validate_search_result import validate_search_results

logger = logging.getLogger(__name__)

GAP_ANALYSIS_SYSTEM = """You are helping a Lexington MA parent find missing youth summer camps.
Given existing camp categories already covered, suggest 5-15 specific Google search queries
to find gaps (categories with zero camps). Focus on local primary sources, not aggregators.

Respond JSON only: {"queries": ["query 1", "query 2", ...]}"""


def _category_from_session(session: dict) -> str | None:
    blob = " ".join(
        x.lower()
        for x in (
            session.get("name", ""),
            session.get("platform", ""),
            session.get("register_url", ""),
        )
    )
    for cat in GAP_CATEGORIES:
        if cat.replace("_", " ") in blob or cat in blob:
            return cat
    if any(w in blob for w in ("sport", "soccer", "basketball", "tennis")):
        return "sports"
    if any(w in blob for w in ("art", "craft", "paint")):
        return "arts"
    if any(w in blob for w in ("robot", "code", "stem", "lego")):
        return "stem"
    return None


def find_missing_categories(registrable_sessions: list[dict]) -> list[str]:
    covered: set[str] = set()
    for s in registrable_sessions:
        cat = _category_from_session(s)
        if cat:
            covered.add(cat)
    return [c for c in GAP_CATEGORIES if c not in covered]


def template_queries(town: str, missing: list[str]) -> list[str]:
    out: list[str] = []
    for cat in missing[:10]:
        tpl = GAP_SEARCH_TEMPLATES.get(cat)
        if tpl:
            out.append(tpl.format(town=town, state=STATE))
    return out


def llm_gap_queries(town: str, missing: list[str], registrable_count: int) -> list[str]:
    if not is_available() or not missing:
        return []
    user = json.dumps(
        {
            "town": town,
            "state": STATE,
            "registrable_sessions": registrable_count,
            "missing_categories": missing[:15],
        }
    )
    try:
        resp = chat(GAP_ANALYSIS_SYSTEM, user, temperature=0.2, timeout=45)
        queries = resp.get("queries", [])
        return [str(q) for q in queries if q][:15]
    except OllamaError as exc:
        logger.warning("gap LLM failed: %s", exc)
        return []


def run_gap_fill(
    town: str,
    *,
    registrable_csv: Path | str | None = None,
    max_searches: int | None = None,
    rounds: int = 2,
    fallback_taxonomy: bool = False,
) -> dict:
    """Run agentic two-pass gap fill (default) or taxonomy-only fallback."""
    if fallback_taxonomy:
        return _run_taxonomy_gap_fill(
            town, registrable_csv=registrable_csv, max_searches=max_searches
        )
    from src.agentic_gap import run_agentic_gap
    from src.parent_verify import load_sessions_for_verify

    sessions = load_sessions_for_verify(town)
    if registrable_csv:
        path = Path(registrable_csv)
        if path.exists():
            import csv as _csv

            with open(path, encoding="utf-8", newline="") as f:
                sessions = list(_csv.DictReader(f))
    return run_agentic_gap(
        town,
        rounds=rounds,
        max_searches=max_searches,
        fallback_taxonomy=False,
        sessions=sessions or None,
    )


def _run_taxonomy_gap_fill(
    town: str,
    *,
    registrable_csv: Path | str | None = None,
    max_searches: int | None = None,
) -> dict:
    from config.settings import SETTINGS as _SETTINGS

    ceiling = max_searches if max_searches is not None else int(
        _SETTINGS.get("gap_max_searches_per_round", 100)
    )
    path = Path(registrable_csv or quality_tier_csv(town, "registrable"))
    sessions: list[dict] = []
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            sessions = list(csv.DictReader(f))

    missing = find_missing_categories(sessions)
    queries = template_queries(town, missing)
    queries.extend(llm_gap_queries(town, missing, len(sessions)))
    queries = list(dict.fromkeys(queries))
    ideal = len(queries)
    planned = min(ideal, ceiling) if ideal else 0
    queries = queries[:planned]

    new_hosts: set[str] = set()
    rows: list[dict] = []
    searches_run = 0
    for q in queries:
        if searches_run >= planned:
            break
        try:
            raw = search(q, SETTINGS["results_per_search"])
        except ConfigError as exc:
            logger.warning("gap search failed %r: %s", q, exc)
            continue
        searches_run += 1
        kept, _ = validate_search_results(raw)
        for item in kept:
            url = normalize_url(item["url"])
            if not url:
                continue
            from urllib.parse import urlparse

            host = urlparse(url).netloc.lower().replace("www.", "")
            if host in new_hosts:
                continue
            new_hosts.add(host)
            rows.append(
                {
                    "url": url,
                    "state": STATE,
                    "town_hint": town,
                    "source_type": "gap_fill",
                    "found_via": "gap",
                    "found_on_page": q,
                    "link_text": item.get("title", ""),
                    "discovered_at": "",
                }
            )

    added = save_new_links(rows) if rows else 0
    return {
        "town": town,
        "missing_categories": missing,
        "ideal_searches": ideal,
        "planned_searches": planned,
        "queries": queries,
        "searches_run": searches_run,
        "new_hosts": len(new_hosts),
        "links_added": added,
    }
