"""Agentic Phase C: two-pass parent audit → search holes → enumerate new hosts."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from config.settings import SETTINGS, STATE
from src.data_layout import (
    gap_audit_json,
    gap_new_sessions_csv,
    refresh_town_index,
    sessions_verified_csv,
    town_slug,
)
from src.discover import ConfigError, search
from src.gap_finder import run_gap_fill as taxonomy_gap_fill
from src.parent_auditor import audit_catalog
from src.parent_verify import load_sessions_for_verify, run_parent_verify
from src.session_quality import write_quality_csvs
from src.sessions import enumerate_town, host_of, write_session_outputs
from src.store import save_new_links
from src.urls import normalize_url
from src.validate_search_result import validate_search_results

logger = logging.getLogger(__name__)

_HOLE_CACHE_PATH = Path("cache/gap_hole_searches.json")


def _load_hole_cache() -> dict[str, str]:
    if not _HOLE_CACHE_PATH.exists():
        return {}
    try:
        with open(_HOLE_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_hole_cache(cache: dict[str, str]) -> None:
    _HOLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_HOLE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def _searchable_holes(
    holes: list[dict],
    *,
    cache: dict[str, str],
    searched_ids: set[str],
) -> list[dict]:
    """Holes that still need a targeted search this round."""
    cache_days = int(SETTINGS.get("gap_hole_cache_days", 7))
    out: list[dict] = []
    for hole in holes:
        hole_id = hole.get("hole_id", "")
        if hole_id in searched_ids:
            continue
        if hole_id and _hole_recently_searched(hole_id, cache, cache_days):
            continue
        if not hole.get("search_query"):
            continue
        out.append(hole)
    return out


def plan_round_searches(
    holes: list[dict],
    *,
    cache: dict[str, str],
    searched_ids: set[str],
    max_ceiling: int,
) -> dict:
    """Size this round: one search per actionable hole, capped at max_ceiling."""
    searchable = _searchable_holes(holes, cache=cache, searched_ids=searched_ids)
    ideal = len(searchable)
    ceiling = max(1, max_ceiling) if max_ceiling else ideal
    planned = min(ideal, ceiling)
    return {
        "searchable_holes": searchable,
        "holes_audited": len(holes),
        "ideal_searches": ideal,
        "planned_searches": planned,
        "max_ceiling": ceiling,
        "deferred_over_ceiling": max(0, ideal - planned),
    }


def _hole_recently_searched(hole_id: str, cache: dict[str, str], days: int) -> bool:
    ts = cache.get(hole_id)
    if not ts:
        return False
    try:
        then = datetime.fromisoformat(ts)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - then < timedelta(days=days)
    except ValueError:
        return False


def _search_holes(
    town: str,
    holes: list[dict],
    *,
    max_searches: int,
    cache: dict[str, str],
    searched_ids: set[str],
) -> tuple[list[dict], set[str], int]:
    """Run searches for pre-filtered holes; return link rows, new hosts, search count."""
    rows: list[dict] = []
    new_hosts: set[str] = set()
    searches_run = 0

    for hole in holes[:max_searches]:
        hole_id = hole.get("hole_id", "")
        query = hole.get("search_query", "")
        if not query:
            continue
        try:
            raw = search(query, SETTINGS["results_per_search"])
        except ConfigError as exc:
            logger.warning("gap search failed %r: %s", query, exc)
            continue
        searches_run += 1
        searched_ids.add(hole_id)
        if hole_id:
            cache[hole_id] = datetime.now(timezone.utc).isoformat()
        kept, _ = validate_search_results(raw)
        for item in kept:
            url = normalize_url(item["url"])
            if not url:
                continue
            host = urlparse(url).netloc.lower().replace("www.", "")
            new_hosts.add(host)
            rows.append(
                {
                    "url": url,
                    "state": STATE,
                    "town_hint": town,
                    "source_type": "gap_agentic",
                    "found_via": "gap",
                    "found_on_page": query,
                    "link_text": item.get("title", ""),
                    "discovered_at": "",
                    "hole_id": hole_id,
                }
            )
    return rows, new_hosts, searches_run


def _merge_sessions(existing: list[dict], new_sessions: list[dict]) -> list[dict]:
    seen = {s.get("register_url", "") for s in existing}
    out = list(existing)
    for s in new_sessions:
        key = s.get("register_url", "")
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _sessions_from_results(results: list[dict]) -> list[dict]:
    out: list[dict] = []
    for res in results:
        for s in res.get("sessions", []):
            out.append(s)
    return out


def _seed_urls_for_hosts(hosts: set[str], town: str) -> list[str]:
    from src.sessions import load_provider_urls

    all_urls = load_provider_urls(town)
    picked: list[str] = []
    for u in all_urls:
        h = host_of(u)
        if h in hosts:
            picked.append(u)
    # Hosts only in gap harvest — use first link URL from rows (caller may pass)
    return picked


async def _enumerate_new_hosts(
    town: str,
    new_hosts: set[str],
    gap_urls: list[str],
) -> list[dict]:
    import asyncio

    urls = list(dict.fromkeys(gap_urls))
    for u in _seed_urls_for_hosts(new_hosts, town):
        if u not in urls:
            urls.append(u)
    if not urls:
        return []
    return await enumerate_town(town, urls=urls)


def run_agentic_gap(
    town: str,
    *,
    rounds: int = 2,
    max_searches: int | None = None,
    fallback_taxonomy: bool = False,
    sessions: list[dict] | None = None,
) -> dict:
    """Two-pass agentic gap fill with dynamic search sizing per round."""
    import asyncio

    slug = town_slug(town)
    ceiling = max_searches if max_searches is not None else int(
        SETTINGS.get("gap_max_searches_per_round", 100)
    )
    sessions = sessions or load_sessions_for_verify(town)
    if fallback_taxonomy and not sessions:
        return taxonomy_gap_fill(town, max_searches=ceiling)

    cache = _load_hole_cache()
    searched_ids: set[str] = set()
    all_new_sessions: list[dict] = []
    round_results: list[dict] = []
    total_searches = 0
    total_links = 0

    for round_num in range(1, rounds + 1):
        audit = audit_catalog(town, sessions, use_llm=not fallback_taxonomy)
        holes = audit.get("holes", [])
        plan = plan_round_searches(
            holes,
            cache=cache,
            searched_ids=searched_ids,
            max_ceiling=ceiling,
        )
        searchable = plan["searchable_holes"]
        planned = plan["planned_searches"]

        logger.info(
            "Gap round %d: %d holes audited, %d need search, running %d (ceiling %d)",
            round_num,
            plan["holes_audited"],
            plan["ideal_searches"],
            planned,
            ceiling,
        )

        if not searchable:
            round_results.append(
                {
                    "round": round_num,
                    "holes_found": len(holes),
                    "ideal_searches": plan["ideal_searches"],
                    "planned_searches": 0,
                    "searches_run": 0,
                    "new_hosts": 0,
                    "new_sessions": 0,
                    "coverage_score": audit.get("coverage_score", 0),
                }
            )
            audit_path = gap_audit_json(town, round_num)
            audit["search_plan"] = plan
            audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
            break

        rows, new_hosts, searches_run = _search_holes(
            town,
            searchable,
            max_searches=planned,
            cache=cache,
            searched_ids=searched_ids,
        )
        total_searches += searches_run
        gap_urls = [r["url"] for r in rows]
        added = save_new_links(
            [{k: v for k, v in r.items() if k != "hole_id"} for r in rows]
        ) if rows else 0
        total_links += added

        new_session_count = 0
        if new_hosts and gap_urls:
            results = asyncio.run(_enumerate_new_hosts(town, new_hosts, gap_urls))
            new_sessions = _sessions_from_results(results)
            new_session_count = len(new_sessions)
            sessions = _merge_sessions(sessions, new_sessions)
            all_new_sessions = _merge_sessions(all_new_sessions, new_sessions)
            write_session_outputs(town, results)
            write_quality_csvs(town, sessions)
            verify_result = asyncio.run(
                run_parent_verify(town, sessions=sessions)
            )
            sessions = load_sessions_for_verify(town, sessions_csv=sessions_verified_csv(town))
            logger.info("Phase P after gap round %d: %s", round_num, verify_result.get("counts"))

        audit_path = gap_audit_json(town, round_num)
        audit["search_plan"] = {
            **plan,
            "searchable_holes": [
                {"hole_id": h.get("hole_id"), "query": h.get("search_query")}
                for h in searchable[:planned]
            ],
        }
        audit["searches_run"] = searches_run
        audit["queries"] = [h.get("search_query") for h in searchable[:planned]]
        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")

        round_results.append(
            {
                "round": round_num,
                "holes_found": len(holes),
                "ideal_searches": plan["ideal_searches"],
                "planned_searches": planned,
                "holes_searched": searches_run,
                "deferred_over_ceiling": plan["deferred_over_ceiling"],
                "new_hosts": len(new_hosts),
                "links_added": added,
                "new_sessions": new_session_count,
                "coverage_score": audit.get("coverage_score", 0),
            }
        )

        if searches_run == 0 or (not new_hosts and round_num == 1):
            break

    _save_hole_cache(cache)

    new_csv = gap_new_sessions_csv(town)
    if all_new_sessions:
        from src.csv_mirror import write_csv_bundle
        from src.sessions import SESSION_CSV_COLUMNS

        write_csv_bundle(
            new_csv,
            all_new_sessions,
            SESSION_CSV_COLUMNS,
            title=f"{town} — new sessions from gap fill",
            description="Net-new camp sessions found in Phase C only.",
        )
    refresh_town_index(town)

    return {
        "town": town,
        "rounds": round_results,
        "total_searches": total_searches,
        "total_links_added": total_links,
        "new_sessions": len(all_new_sessions),
        "final_session_count": len(sessions),
    }
