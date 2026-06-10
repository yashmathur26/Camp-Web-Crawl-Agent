"""Camp Link Discovery Engine — orchestrator and CLI entrypoint."""

import argparse
import asyncio
import csv
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import tldextract

from config.keywords import PHASE_A_KEYWORDS, PHASE_C_KEYWORDS
from config.settings import SETTINGS, STATE
from config.sources import (
    DIRECTORY_CRAWL_PREFERRED_PATHS,
    DIRECTORY_CRAWL_SKIP_PATH_PATTERNS,
)
from config.towns import TOWNS
from src.cache import get_cached_search_results, load_seen_urls, record_search
from src.candidate_outputs import write_candidates_txt
from src.classify import classify
from src.camp_hosts import is_camp_host_seed_url, is_rec_center_host
from src.camp_validator import filter_rows_with_llm, make_link_follow_gate
from src.crawl import fetch_page_text, harvest_guide_outbound, walk_site
from src.crawl_scheduler import crawl_profile, seed_tier, should_skip_seed, sort_seeds
from src import harvest_activity, harvest_log
from src.discover import ConfigError, search
from src.filter_links import is_external_camp_lead, is_likely_camp_link
from src.link_quality import is_quality_camp_link
from src.geo_filter import is_out_of_state_url
from src.registration import is_registration_platform_url, registration_url_priority
from src import data_layout
from src.csv_mirror import mirror_csv_to_txt
from src.store import count_camp_links, save_new_links
from src.urls import normalize_url
from src.validate_search_result import validate_search_results

CANDIDATES_PATH = data_layout.candidates_csv()
REJECTED_PATH = data_layout.rejected_candidates_csv()
CANDIDATES_COLUMNS = [
    "url",
    "state",
    "town",
    "keyword",
    "phase",
    "classified_as",
    "crawled",
    "discovered_at",
    "title",
    "preferred",
]

REJECTED_COLUMNS = [
    "url",
    "title",
    "snippet",
    "town",
    "keyword",
    "phase",
    "reason",
    "source_type",
    "discovered_at",
]

LOG_DIR = data_layout.LOGS_ROOT


class RunStats:
    def __init__(self) -> None:
        self.searches_used = 0
        self.pages_crawled = 0
        self.new_links_a = 0
        self.new_links_b = 0
        self.new_links_c = 0
        self.skipped_sources = 0
        self.rejected_results = 0
        self.sessions_enumerated = 0
        self.start_time = time.monotonic()

    @property
    def est_cost_usd(self) -> float:
        return self.searches_used * SETTINGS["cost_per_query_usd"]

    @property
    def runtime_s(self) -> float:
        return time.monotonic() - self.start_time


def setup_logging(
    *,
    agent: bool = False,
    log_file: Path | None = None,
    quiet_crawlers: bool = True,
    console: bool = True,
) -> Path:
    data_layout.logs_root_readme()
    data_layout.data_root_readme()
    if log_file is None:
        log_file = data_layout.run_log_path(agent=agent)
    else:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    if console:
        root.addHandler(stream_handler)

    if quiet_crawlers:
        for name in ("crawl4ai", "httpx", "httpcore", "urllib3", "playwright"):
            logging.getLogger(name).setLevel(logging.WARNING)

    return log_file


def _load_candidates() -> list[dict]:
    if not CANDIDATES_PATH.exists():
        return []
    with open(CANDIDATES_PATH, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _save_candidates(rows: list[dict]) -> None:
    CANDIDATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CANDIDATES_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATES_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    write_candidates_txt(rows, txt_path=CANDIDATES_PATH.with_suffix(".txt"))


def _append_candidates(new_rows: list[dict]) -> None:
    existing = _load_candidates()
    existing_urls = {normalize_url(r["url"]) for r in existing}
    for row in new_rows:
        norm = normalize_url(row["url"])
        if norm not in existing_urls:
            existing.append(row)
            existing_urls.add(norm)
    _save_candidates(existing)


def _append_rejected(rows: list[dict]) -> None:
    if not rows:
        return
    REJECTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if REJECTED_PATH.exists():
        with open(REJECTED_PATH, encoding="utf-8", newline="") as f:
            existing = list(csv.DictReader(f))
    existing.extend(rows)
    with open(REJECTED_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REJECTED_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing)
    mirror_csv_to_txt(
        REJECTED_PATH,
        title="Rejected search results",
        description="Phase A hits dropped at ingest.",
    )


def _matches_hosts(url: str, host_filters: list[str] | None) -> bool:
    if not host_filters:
        return True
    domain = _registered_domain(url).lower()
    blob = f"{domain}{urlparse(url).path}".lower()
    return any(h in domain or h in blob for h in host_filters)


def _registered_domain(url: str) -> str:
    parsed = urlparse(url)
    ext = tldextract.extract(parsed.netloc)
    if not ext.domain or not ext.suffix:
        return parsed.netloc.lower()
    return f"{ext.domain}.{ext.suffix}".lower()


def _directory_seed_score(url: str) -> int:
    path = urlparse(url).path.lower()
    score = 0
    for pattern in DIRECTORY_CRAWL_SKIP_PATH_PATTERNS:
        if pattern in path:
            score += 100
    for preferred in DIRECTORY_CRAWL_PREFERRED_PATHS:
        if preferred in path:
            score -= 20
    if path in ("", "/"):
        score += 50
    if is_camp_host_seed_url(url):
        score -= 40
    return score


def _filter_directory_seeds(
    pending: list[tuple[int, dict]],
) -> tuple[list[tuple[int, dict]], list[tuple[int, dict]]]:
    """Keep camp-host seeds + one directory seed per domain; skip blog/nav hubs."""
    guides: list[tuple[int, dict]] = []
    camp_hosts: list[tuple[int, dict]] = []
    camp_host_urls: set[str] = set()
    by_domain: dict[str, list[tuple[int, tuple[int, dict]]]] = {}
    skip: list[tuple[int, dict]] = []
    kept_by_domain: dict[str, str] = {}

    for item in pending:
        candidate = item[1]
        if candidate.get("classified_as") == "guide":
            guides.append(item)
            continue
        url = candidate["url"]
        score = _directory_seed_score(url)
        if score >= 100:
            skip.append(item)
            continue
        if is_camp_host_seed_url(url) or candidate.get("classified_as") == "camp":
            norm = normalize_url(url)
            if norm and norm not in camp_host_urls:
                camp_hosts.append(item)
                camp_host_urls.add(norm)
                harvest_log.camp_host_seed_kept(url)
            else:
                skip.append(item)
            continue
        domain = _registered_domain(url)
        by_domain.setdefault(domain, []).append((score, item))

    best: list[tuple[int, dict]] = []
    for domain, scored in by_domain.items():
        scored.sort(key=lambda x: x[0])
        kept = scored[0][1]
        best.append(kept)
        kept_by_domain[domain] = kept[1]["url"]
        for _, dup in scored[1:]:
            skip.append(dup)

    for item in skip:
        dup_url = item[1]["url"]
        domain = _registered_domain(dup_url)
        harvest_log.duplicate_seed_skipped(dup_url, kept_by_domain.get(domain))

    return guides + camp_hosts + best, skip


def _row_from_candidate(
    candidate: dict, url: str, *, source_type: str, found_on: str, link_text: str = ""
) -> dict:
    return {
        "url": url,
        "state": STATE,
        "town_hint": candidate.get("town", ""),
        "source_type": source_type,
        "found_via": candidate.get("phase", ""),
        "found_on_page": found_on,
        "link_text": link_text or candidate.get("title", ""),
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


def _cap_rows_by_domain(rows: list[dict]) -> list[dict]:
    cap = SETTINGS["max_links_per_domain_per_harvest"]
    counts: defaultdict[str, int] = defaultdict(int)
    kept: list[dict] = []
    for row in rows:
        domain = _registered_domain(row.get("url", ""))
        if counts[domain] >= cap:
            continue
        counts[domain] += 1
        kept.append(row)
    return kept


def _build_queries(
    keywords: list[str], towns: list[str] | None = None
) -> list[tuple[str, str, str]]:
    """Return list of (query, town, keyword)."""
    town_list = towns if towns is not None else TOWNS
    queries = []
    for town in town_list:
        for keyword in keywords:
            queries.append((f"{keyword} {town}, {STATE}", town, keyword))
    return queries


def _run_discovery_phase(
    phase: str,
    keywords: list[str],
    stats: RunStats,
    dry_run: bool,
    search_limit: int | None,
    seen_url_set: set[str],
    towns: list[str] | None = None,
) -> None:
    if not keywords:
        logging.info("Phase %s skipped: no keywords configured", phase)
        return

    queries = _build_queries(keywords, towns)
    planned = len(queries)
    est_cost = planned * SETTINGS["cost_per_query_usd"]
    logging.info(
        "Phase %s: %d planned queries, est cost $%.4f",
        phase,
        planned,
        est_cost,
    )

    if dry_run:
        print(f"\n=== DRY RUN — Phase {phase} ===")
        print(f"Planned queries: {planned}")
        print(f"Estimated cost:  ${est_cost:.4f}")
        print("No network calls will be made.\n")
        return

    rejected_rows: list[dict] = []
    total_candidates = 0
    now = datetime.now(timezone.utc).isoformat()

    for qi, (query, town, keyword) in enumerate(queries, 1):
        if search_limit is not None and stats.searches_used >= search_limit:
            logging.info("Search limit (%d) reached", search_limit)
            break
        if stats.searches_used >= SETTINGS["max_searches_per_run"]:
            logging.info(
                "max_searches_per_run (%d) reached",
                SETTINGS["max_searches_per_run"],
            )
            break

        cached = get_cached_search_results(query)
        if cached is not None:
            raw_results = cached
            logging.info("Phase %s [%d/%d] cache hit: %s", phase, qi, planned, query)
        else:
            try:
                raw_results = search(query, SETTINGS["results_per_search"])
            except ConfigError as exc:
                logging.warning("Search failed for %r: %s", query, exc)
                continue

            record_search(query, raw_results)
            stats.searches_used += 1

        kept, validation = validate_search_results(raw_results)
        if SETTINGS.get("phase_a_llm_judge"):
            from src.agent_tools import _llm_judge_results

            unknown = [i for i in kept if i.get("source_type") == "unknown"]
            if unknown:
                judged = _llm_judge_results(query, unknown)
                preferred = [i for i in kept if i.get("source_type") != "unknown"]
                kept = preferred + judged
        for v in validation:
            if v.verdict == "reject":
                stats.rejected_results += 1
                rejected_rows.append(
                    {
                        "url": v.url,
                        "title": next(
                            (r.get("title", "") for r in raw_results if normalize_url(r.get("url", "")) == v.url),
                            "",
                        ),
                        "snippet": next(
                            (r.get("snippet", "") for r in raw_results if normalize_url(r.get("url", "")) == v.url),
                            "",
                        ),
                        "town": town,
                        "keyword": keyword,
                        "phase": phase,
                        "reason": v.reason,
                        "source_type": v.source_type,
                        "discovered_at": now,
                    }
                )

        query_candidates: list[dict] = []
        for item in kept:
            normalized = item["url"]
            if phase == "C" and normalized in seen_url_set:
                continue
            if item.get("source_type") == "guide":
                classified = "guide"
            else:
                classified = classify(normalized)
            if classified == "camp" and phase == "C":
                if normalized in seen_url_set:
                    continue
            query_candidates.append(
                {
                    "url": normalized,
                    "state": STATE,
                    "town": town,
                    "keyword": keyword,
                    "phase": phase,
                    "classified_as": classified,
                    "crawled": "false",
                    "discovered_at": now,
                    "title": item.get("title", ""),
                    "preferred": "true" if item.get("preferred") else "false",
                }
            )
            if phase == "C":
                seen_url_set.add(normalized)

        if query_candidates:
            _append_candidates(query_candidates)
            total_candidates += len(query_candidates)

        logging.info(
            "Phase %s [%d/%d] %s — +%d candidates (%d paid searches)",
            phase,
            qi,
            planned,
            "cached" if cached is not None else "searched",
            len(query_candidates),
            stats.searches_used,
        )

    if rejected_rows:
        _append_rejected(rejected_rows)
        logging.info("Phase %s: rejected %d search results", phase, len(rejected_rows))

    if total_candidates:
        logging.info("Phase %s: added %d candidate rows total", phase, total_candidates)


async def _harvest_candidates(
    phase_filter: str | None,
    stats: RunStats,
    dry_run: bool,
    town_filter: str | None = None,
    host_filters: list[str] | None = None,
    preferred_only: bool = False,
) -> int:
    crawlable = ("directory", "unknown", "guide", "camp")
    if dry_run:
        candidates = [
            c
            for c in _load_candidates()
            if c.get("crawled", "false") == "false"
            and c.get("classified_as") in crawlable
            and (phase_filter is None or c.get("phase") == phase_filter)
            and (town_filter is None or c.get("town") == town_filter)
            and _matches_hosts(c.get("url", ""), host_filters)
        ]
        print(f"\n=== DRY RUN — Harvest ===")
        host_note = f" (hosts: {', '.join(host_filters)})" if host_filters else ""
        print(f"Would crawl {len(candidates)} directory/unknown/guide candidates{host_note}")
        return 0

    candidates = _load_candidates()
    new_link_count = 0
    updated = False

    pending = [
        (i, c)
        for i, c in enumerate(candidates)
        if c.get("crawled", "false") == "false"
        and c.get("classified_as") in crawlable
        and (phase_filter is None or c.get("phase") == phase_filter)
        and (town_filter is None or c.get("town") == town_filter)
        and _matches_hosts(c.get("url", ""), host_filters)
        and (not preferred_only or c.get("preferred") == "true" or seed_tier(c) in ("preferred", "camp_host"))
    ]
    if host_filters:
        logging.info("Host filter: %s (%d sources)", ", ".join(host_filters), len(pending))
    # Primary/preferred sources first, then directories, then guides last.
    def _order(c: dict) -> tuple:
        is_guide = c.get("classified_as") == "guide"
        return (is_guide, c.get("preferred") != "true", c.get("url", ""))

    pending.sort(key=lambda x: _order(x[1]))
    pending = sort_seeds(pending)
    already_crawled = sum(
        1
        for c in candidates
        if c.get("crawled", "false") == "true"
        and c.get("classified_as") in crawlable
        and (phase_filter is None or c.get("phase") == phase_filter)
        and (town_filter is None or c.get("town") == town_filter)
        and _matches_hosts(c.get("url", ""), host_filters)
    )

    pending, skipped_seeds = _filter_directory_seeds(pending)
    harvest_log.run_banner(
        phase="B",
        town=town_filter,
        llm=bool(SETTINGS.get("ollama_validate_links")),
        already_crawled=already_crawled,
        pending=len(pending),
    )
    if skipped_seeds:
        logging.info(
            "Phase B: %d duplicate seeds skipped, %d sources queued",
            len(skipped_seeds),
            len(pending),
        )
    for i, candidate in skipped_seeds:
        candidates[i]["crawled"] = "true"
        updated = True
    if updated:
        _save_candidates(candidates)
        updated = False

    for i, candidate in pending:
        url = candidate["url"]
        skip, skip_reason = should_skip_seed(candidate, state=STATE)
        if skip:
            harvest_log.geo_skipped(url=url, reason=skip_reason, town=candidate.get("town", ""))
            candidates[i]["crawled"] = "true"
            _save_candidates(candidates)
            continue
        if SETTINGS.get("geo_filter_crawl"):
            oos, oos_reason = is_out_of_state_url(
                url,
                title=candidate.get("title", ""),
                state=STATE,
            )
            if oos:
                harvest_log.geo_skipped(
                    url=url, reason=oos_reason, town=candidate.get("town", "")
                )
                candidates[i]["crawled"] = "true"
                _save_candidates(candidates)
                continue

        is_guide = candidate.get("classified_as") == "guide"
        rows_to_store: list[dict] = []
        page_text_by_url: dict[str, str] = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        rule_kept = 0

        harvest_log.source_start(
            url=url,
            kind="guide" if is_guide else candidate.get("classified_as", "directory"),
            town=candidate.get("town", ""),
            title=candidate.get("title", ""),
        )

        if is_guide:
            try:
                outbound = await harvest_guide_outbound(url)
            except Exception as exc:
                logging.warning("Guide harvest failed for %s: %s", url, exc)
                harvest_log.guide_failed(url, str(exc), town=candidate.get("town", ""))
                stats.skipped_sources += 1
                continue
            stats.pages_crawled += 1
            for link in outbound:
                if not is_external_camp_lead(url, link["url"], link.get("text", "")):
                    continue
                rows_to_store.append(
                    {
                        "url": link["url"],
                        "state": STATE,
                        "town_hint": candidate.get("town", ""),
                        "source_type": "guide_referral",
                        "found_via": candidate.get("phase", ""),
                        "found_on_page": url,
                        "link_text": link.get("text", ""),
                        "discovered_at": now_iso,
                    }
                )
                rule_kept += 1
        else:
            seed_is_camp_host = (
                is_camp_host_seed_url(url)
                or candidate.get("classified_as") == "camp"
                or is_rec_center_host(url)
            )
            tier = seed_tier(candidate)
            if candidate.get("classified_as") == "guide":
                tier = "guide"
            profile = crawl_profile(tier)
            use_focused = profile.get("focused", seed_is_camp_host)
            max_pages = int(profile.get("max_pages", SETTINGS["max_pages_per_source"]))
            max_depth = int(profile.get("max_depth", SETTINGS["max_crawl_depth"]))
            delay = float(profile.get("delay_seconds", SETTINGS["delay_seconds"]))
            link_follow = profile.get("ollama_link_follow", SETTINGS.get("ollama_link_follow"))

            try:
                if use_focused:
                    walk = await walk_site(
                        url,
                        max_depth,
                        max_pages,
                        focused=True,
                        delay_seconds=delay,
                        stop_on_catalog=profile.get("stop_on_catalog", SETTINGS["focused_stop_on_catalog"]),
                        link_gate=make_link_follow_gate() if link_follow else None,
                    )
                else:
                    walk = await walk_site(url, max_depth, max_pages, delay_seconds=delay)
                links = walk.links
                page_text_by_url = walk.page_text_by_url
            except Exception as exc:
                logging.warning("Crawl failed for %s: %s", url, exc)
                harvest_log.crawl_failed(url, str(exc))
                stats.skipped_sources += 1
                # Leave crawled=false so a retry can pick this source up again.
                continue

            stats.pages_crawled += min(len(links), SETTINGS["max_pages_per_source"])
            registration_rows: list[dict] = []
            directory_rows: list[dict] = []
            for link in links:
                if not is_likely_camp_link(link["url"], link.get("text", "")):
                    continue
                norm = normalize_url(link["url"])
                if norm == normalize_url(url):
                    continue
                row = {
                    "url": link["url"],
                    "state": STATE,
                    "town_hint": candidate.get("town", ""),
                    "source_type": (
                        "registration"
                        if is_registration_platform_url(link["url"])
                        else "directory"
                    ),
                    "found_via": candidate.get("phase", ""),
                    "found_on_page": url,
                    "link_text": link.get("text", ""),
                    "discovered_at": now_iso,
                }
                if row["source_type"] == "registration":
                    registration_rows.append(row)
                else:
                    directory_rows.append(row)

            if registration_rows:
                rows_to_store.extend(registration_rows)
            elif seed_is_camp_host:
                rows_to_store.append(
                    _row_from_candidate(
                        candidate,
                        url,
                        source_type="camp_host",
                        found_on=url,
                    )
                )
            rows_to_store.extend(directory_rows)

            harvest_log.crawl_stats(
                pages=len(page_text_by_url),
                links_found=len(links),
                heuristic_kept=len(registration_rows) + len(directory_rows),
            )
            rule_kept = len(rows_to_store)
            rows_to_store.sort(
                key=lambda r: registration_url_priority(r.get("url", "")),
                reverse=True,
            )

        pre_cap = len(rows_to_store)
        rows_to_store = _cap_rows_by_domain(rows_to_store)
        rows_to_store = [
            r
            for r in rows_to_store
            if is_quality_camp_link(r.get("url", ""), r.get("link_text", ""))
        ]
        if pre_cap and len(rows_to_store) < pre_cap:
            logging.debug(
                "Quality filter dropped %d slop link(s) for %s",
                pre_cap - len(rows_to_store),
                url,
            )
        rows_to_store, llm_rejected = await filter_rows_with_llm(
            rows_to_store,
            page_text_by_url,
            fetch_page_text=fetch_page_text,
        )
        for row in rows_to_store:
            harvest_log.link_saved(
                row["url"],
                row.get("link_text", ""),
                row.get("source_type", ""),
            )
        added = save_new_links(rows_to_store)
        new_link_count += added
        candidates[i]["crawled"] = "true"
        _save_candidates(candidates)
        harvest_log.source_summary(
            url=url,
            added=added,
            rule_kept=rule_kept,
            llm_rejected=llm_rejected,
            llm_kept=len(rows_to_store),
            is_guide=is_guide,
        )

    return new_link_count


def _run_quality_gate(town_name: str, results: list[dict]) -> None:
    from src.session_quality import enrollability_score, write_quality_csvs

    sessions: list[dict] = []
    for res in results:
        for s in res.get("sessions", []):
            sessions.append(s)
    paths = write_quality_csvs(town_name, sessions)
    score, counts = enrollability_score(sessions)
    logging.info("Phase Q: enrollability %d/100 — %s", score, counts)
    print(f"\n=== PHASE Q: quality gate ({town_name}) ===")
    for tier, path in paths.items():
        print(f"  {tier}: {path}")
    print(f"Enrollability score: {score}/100\n")


def _run_registration_trail(town_name: str, results: list[dict]) -> None:
    from src.registration_trail import merge_trail_sessions, run_registration_trail

    zero_seeds = [r["url"] for r in results if not r.get("sessions")]
    logging.info("Phase B.6 trail: %d zero-session + needs_trail seeds", len(zero_seeds))
    print(f"\n=== PHASE B.6: registration trail ({town_name}) ===\n")
    trail_results = asyncio.run(run_registration_trail(town_name, zero_session_seeds=zero_seeds))
    recovered = merge_trail_sessions(trail_results)
    print(f"Recovered {len(recovered)} registrable session(s) from trail\n")


def _run_parent_verify(
    town_name: str,
    *,
    verify_all: bool = False,
    max_llm: int | None = None,
) -> None:
    from src.parent_verify import run_parent_verify

    print(f"\n=== PHASE P: parent verify ({town_name}) ===\n")
    result = asyncio.run(
        run_parent_verify(
            town_name,
            verify_all=verify_all,
            max_llm=max_llm,
        )
    )
    print(f"Parent verify counts: {result['counts']}")
    for verdict, path in result.get("paths", {}).items():
        print(f"  {verdict}: {path}")
    print()


def _run_gap_fill(
    town_name: str,
    *,
    max_searches: int | None = None,
    gap_rounds: int = 2,
    fallback_taxonomy: bool = False,
) -> None:
    from src.gap_finder import run_gap_fill

    print(f"\n=== PHASE C agentic gap-fill ({town_name}) ===\n")
    result = run_gap_fill(
        town_name,
        max_searches=max_searches,
        rounds=gap_rounds,
        fallback_taxonomy=fallback_taxonomy,
    )
    if "rounds" in result:
        for r in result["rounds"]:
            ideal = r.get("ideal_searches", "?")
            planned = r.get("planned_searches", r.get("holes_searched", "?"))
            print(
                f"  Round {r.get('round')}: {r.get('holes_found', 0)} holes, "
                f"{ideal} need search, ran {planned}"
            )
        print(
            f"Total: {result.get('total_searches', 0)} searches, "
            f"{result.get('new_sessions', 0)} new sessions\n"
        )
    else:
        print(
            f"Gap-fill: {result.get('searches_run', 0)} searches, "
            f"{result.get('links_added', 0)} new links\n"
        )


def _warmup_ollama_models() -> None:
    if not SETTINGS.get("ollama_preload_models"):
        return
    from src.llm import chat, is_available, resolve_model

    if not is_available():
        logging.warning(
            "Ollama not reachable at %s — LLM steps will use rules-only fallbacks",
            SETTINGS["ollama_base_url"],
        )
        return
    warmed: set[str] = set()
    for model in (
        SETTINGS.get("ollama_fast_model"),
        SETTINGS.get("ollama_verify_model") or SETTINGS.get("ollama_filter_model"),
    ):
        if not model:
            continue
        resolved = resolve_model(model)
        if resolved in warmed:
            continue
        try:
            chat("Respond JSON: {}", "{}", model=resolved, timeout=30, num_predict=8)
            logging.info("Warmed up model: %s", resolved)
            warmed.add(resolved)
        except Exception as exc:  # noqa: BLE001
            logging.warning("Model warmup failed for %s: %s", resolved, exc)


def _run_session_enumeration(
    town_name: str,
    stats: RunStats,
    *,
    post_phases: bool = False,
    verify_all: bool = False,
    verify_max_llm: int | None = None,
    gap_rounds: int = 2,
    max_searches: int | None = None,
    gap_fallback_taxonomy: bool = False,
) -> list[dict]:
    """Phase B.5: platform-aware per-camp session enumeration for one town.

    Reads every provider candidate for the town (any discovery phase) and writes
    data/<town>_camp_sessions.{csv,txt}. Shared by the B, C, and all flows."""
    from src.sessions import (
        enumerate_town,
        print_enumeration_summary,
        write_session_outputs,
    )

    slug = town_name.lower().replace(" ", "_")
    session_log_path = data_layout.session_log_path(town_name)
    logging.info("Phase B.5: enumerating camp sessions for %s", town_name)
    print(f"\n=== PHASE B.5: enumerate sessions ({town_name}) ===")
    print(f"Detailed log: {session_log_path}\n")
    # Several providers 403 the default bot user-agent.
    if "FindFireflyBot" in SETTINGS.get("user_agent", ""):
        SETTINGS["user_agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    results = asyncio.run(enumerate_town(town_name, log_file=session_log_path))
    stats.sessions_enumerated = print_enumeration_summary(results)
    csv_path, txt_path, total = write_session_outputs(town_name, results)
    logging.info("Phase B.5 wrote %s (%d sessions)", csv_path, total)
    print(f"Wrote {csv_path}\nWrote {txt_path}")
    print(f"Detailed log: {session_log_path}\n")

    from src.deliverables import write_deliverables

    bundle_dir = write_deliverables(town_name, results)
    logging.info("Deliverables bundle: %s", bundle_dir)
    print(f"Deliverables folder: {bundle_dir}/")
    print("  → README.txt, CAMPS_CATALOG.txt, QUALITY_REPORT.txt, organized CSVs\n")

    _run_quality_gate(town_name, results)

    from src.pilot_analysis import update_pilot_analysis

    analysis_path = update_pilot_analysis(
        town_name,
        run_status="COMPLETE",
        stats={
            "sessions_enumerated": stats.sessions_enumerated,
            "total_camp_links": count_camp_links(),
        },
    )
    logging.info("Pilot analysis: %s", analysis_path)
    print(f"Pilot analysis: {analysis_path}\n")

    if post_phases:
        _run_parent_verify(town_name, verify_all=verify_all, max_llm=verify_max_llm)
        _run_registration_trail(town_name, results)
        _run_gap_fill(
            town_name,
            max_searches=max_searches,
            gap_rounds=gap_rounds,
            fallback_taxonomy=gap_fallback_taxonomy,
        )
    return results


def _process_direct_camp_candidates(
    phase: str, stats: RunStats, dry_run: bool
) -> int:
    """Store camp-classified search results directly (Phase C gap-fill)."""
    if dry_run:
        return 0

    candidates = _load_candidates()
    new_count = 0
    updated = False
    now = datetime.now(timezone.utc).isoformat()

    for i, candidate in enumerate(candidates):
        if candidate.get("phase") != phase:
            continue
        if candidate.get("classified_as") != "camp":
            continue
        if candidate.get("crawled", "false") == "true":
            continue

        rows = [
            {
                "url": candidate["url"],
                "state": STATE,
                "town_hint": candidate.get("town", ""),
                "source_type": "search",
                "found_via": phase,
                "found_on_page": "",
                "link_text": "",
                "discovered_at": now,
            }
        ]
        added = save_new_links(rows)
        new_count += added
        candidates[i]["crawled"] = "true"
        updated = True

    if updated:
        _save_candidates(candidates)
    return new_count


def print_summary(stats: RunStats, *, town: str | None = None, dry_run: bool = False) -> None:
    total = count_camp_links()
    harvest_log.run_summary(
        searches_used=stats.searches_used,
        pages_crawled=stats.pages_crawled,
        new_links_b=stats.new_links_b,
        total_camp_links=total,
        skipped_sources=stats.skipped_sources,
        runtime_s=round(stats.runtime_s, 1),
    )
    print("\n=== RUN SUMMARY ===")
    print(f"searches_used:      {stats.searches_used}")
    print(f"est_cost_usd:       ${stats.est_cost_usd:.4f}")
    print(f"rejected_results:   {stats.rejected_results}")
    print(f"pages_crawled:      {stats.pages_crawled}")
    print(f"new_links_phase_a:  {stats.new_links_a}")
    print(f"new_links_phase_b:  {stats.new_links_b}")
    print(f"new_links_phase_c:  {stats.new_links_c}")
    print(f"total_camp_links:   {total}")
    print(f"sessions_enumerated:{stats.sessions_enumerated}")
    print(f"runtime_s:          {stats.runtime_s:.1f}")
    print(f"skipped_sources:    {stats.skipped_sources}")
    print("===================\n")

    if town and not dry_run:
        from src.pilot_analysis import update_pilot_analysis

        status = "COMPLETE" if stats.sessions_enumerated else "IN PROGRESS or Phase B only"
        update_pilot_analysis(
            town,
            run_status=status,
            stats={
                "sessions_enumerated": stats.sessions_enumerated,
                "total_camp_links": total,
                "runtime_s": round(stats.runtime_s, 1),
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Camp Link Discovery Engine")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Plan only, no network calls",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Execute live searches and crawls",
    )
    parser.add_argument(
        "--phase",
        choices=["A", "B", "B5", "Q", "verify", "P", "trail", "gap", "C", "all"],
        default="all",
        help="Which phase(s) to run (verify/P = parent enrollment check)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max paid searches this run",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Run autonomous Ollama agent instead of scripted pipeline",
    )
    parser.add_argument(
        "--town",
        type=str,
        default=None,
        help="Run for a single town only (e.g. Lexington)",
    )
    parser.add_argument(
        "--no-llm-validate",
        action="store_true",
        help="Disable Ollama camp-page filter during Phase B harvest",
    )
    parser.add_argument(
        "--llm-validate",
        action="store_true",
        help="Enable Ollama camp-page filter during Phase B harvest",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Write detailed harvest log to this path (default: logs/run_<date>.log)",
    )
    parser.add_argument(
        "--reset-links",
        action="store_true",
        help="Clear camp_links.csv and seen_urls cache before run",
    )
    parser.add_argument(
        "--activity-csv",
        type=str,
        default=None,
        help="Append harvest events to this CSV (default: data/harvest_activity_<date>.csv)",
    )
    parser.add_argument(
        "--hosts",
        type=str,
        default=None,
        help="Comma-separated host substrings; only crawl matching sources (e.g. jwhayden,ymca)",
    )
    parser.add_argument(
        "--enumerate-sessions",
        action="store_true",
        help="Run Phase B.5: enumerate per-camp session links after harvest",
    )
    parser.add_argument(
        "--no-enumerate-sessions",
        action="store_true",
        help="Skip Phase B.5 session enumeration",
    )
    parser.add_argument(
        "--preferred-only",
        action="store_true",
        help="Phase B: crawl preferred/camp_host seeds only (skip unknown)",
    )
    parser.add_argument(
        "--max-searches",
        type=int,
        default=None,
        help="Ceiling per gap round (default: 100; actual = holes found, not blind fill)",
    )
    parser.add_argument(
        "--gap-rounds",
        type=int,
        default=None,
        help="Agentic gap-fill passes (default: 2)",
    )
    parser.add_argument(
        "--gap-fallback-taxonomy",
        action="store_true",
        help="Use static taxonomy gap-fill instead of parent auditor",
    )
    parser.add_argument(
        "--verify-all",
        action="store_true",
        help="LLM-verify every session URL (not just ambiguous rows)",
    )
    parser.add_argument(
        "--verify-max-llm",
        type=int,
        default=None,
        help="Cap LLM calls for --phase verify",
    )
    args = parser.parse_args()
    gap_rounds = args.gap_rounds if args.gap_rounds is not None else int(
        SETTINGS.get("gap_rounds_default", 2)
    )
    host_filters: list[str] | None = None
    if args.hosts:
        host_filters = [h.strip().lower() for h in args.hosts.split(",") if h.strip()]

    town_filter: list[str] | None = None
    if args.town:
        match = next((t for t in TOWNS if t.lower() == args.town.lower()), None)
        if match is None:
            print(f"Unknown town: {args.town!r}. Must be one of {len(TOWNS)} configured towns.", file=sys.stderr)
            sys.exit(1)
        town_filter = [match]

    # Phase B.5 defaults on for single-town live runs unless explicitly disabled.
    enumerate_sessions = bool(town_filter) and not args.no_enumerate_sessions
    if args.enumerate_sessions:
        enumerate_sessions = True

    if args.no_dry_run:
        dry_run = False
    elif args.dry_run:
        dry_run = True
    else:
        dry_run = SETTINGS["dry_run"]

    if args.no_llm_validate:
        SETTINGS["ollama_validate_links"] = False
    elif args.llm_validate:
        SETTINGS["ollama_validate_links"] = True

    log_path = setup_logging(
        agent=args.agent,
        log_file=Path(args.log_file) if args.log_file else None,
        # --log-file already writes to disk; stdout mirror duplicates lines when
        # the shell also redirects (e.g. nohup ... >> same.log).
        console=args.log_file is None,
    )
    run_phase = args.phase
    if args.activity_csv:
        activity_path = Path(args.activity_csv)
    elif run_phase in ("B", "all") and not args.agent:
        activity_path = data_layout.harvest_activity_csv()
    else:
        activity_path = None
    if activity_path is not None:
        harvest_activity.init(activity_path)
        logging.info("Activity CSV: %s", activity_path)
    if args.reset_links and not dry_run:
        from src.store import DEFAULT_CAMP_LINKS_PATH

        seen_path = Path("cache/seen_urls.json")
        DEFAULT_CAMP_LINKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEFAULT_CAMP_LINKS_PATH, "w", encoding="utf-8") as f:
            f.write(
                "url,state,town_hint,source_type,found_via,found_on_page,link_text,status,discovered_at\n"
            )
        seen_path.parent.mkdir(parents=True, exist_ok=True)
        seen_path.write_text("[]", encoding="utf-8")
        logging.info("Reset camp_links.csv and seen_urls cache")

    stats = RunStats()
    seen_url_set = load_seen_urls()

    logging.info("Log file: %s", log_path)
    logging.info(
        "Starting run (dry_run=%s, phase=%s, limit=%s, agent=%s, town=%s, llm=%s)",
        dry_run,
        run_phase,
        args.limit,
        args.agent,
        town_filter[0] if town_filter else "all",
        SETTINGS.get("ollama_validate_links"),
    )

    if not dry_run and run_phase in ("A", "B", "all", "B5", "verify", "P", "gap", "C"):
        _warmup_ollama_models()

    try:
        if args.agent:
            from src.agent import run_agent

            result = asyncio.run(run_agent(search_limit=args.limit, dry_run=dry_run))
            print("\n=== AGENT SUMMARY ===")
            for key, val in result.items():
                print(f"{key}: {val}")
            print("=====================\n")
            return

        if run_phase in ("A", "all"):
            _run_discovery_phase(
                "A", PHASE_A_KEYWORDS, stats, dry_run, args.limit, seen_url_set, town_filter
            )

        if run_phase in ("B", "all") and not dry_run:
            town_name = town_filter[0] if town_filter else None
            stats.new_links_b = asyncio.run(
                _harvest_candidates(
                    "A", stats, dry_run, town_name, host_filters,
                    preferred_only=args.preferred_only,
                )
            )
            seen_url_set = load_seen_urls()
        elif run_phase in ("B", "all") and dry_run:
            town_name = town_filter[0] if town_filter else None
            asyncio.run(
                _harvest_candidates(
                    "A", stats, dry_run, town_name, host_filters,
                    preferred_only=args.preferred_only,
                )
            )

        if run_phase == "B5" and town_filter and not dry_run:
            _run_session_enumeration(town_filter[0], stats)

        if run_phase == "Q" and town_filter and not dry_run:
            from src.sessions import enumerate_town, write_session_outputs
            results = asyncio.run(enumerate_town(town_filter[0]))
            write_session_outputs(town_filter[0], results)
            _run_quality_gate(town_filter[0], results)

        if run_phase == "trail" and town_filter and not dry_run:
            from src.sessions import enumerate_town
            results = asyncio.run(enumerate_town(town_filter[0]))
            _run_registration_trail(town_filter[0], results)

        if run_phase in ("verify", "P") and town_filter and not dry_run:
            _run_parent_verify(
                town_filter[0],
                verify_all=args.verify_all,
                max_llm=args.verify_max_llm,
            )

        if run_phase == "gap" and town_filter and not dry_run:
            _run_gap_fill(
                town_filter[0],
                max_searches=args.max_searches,
                gap_rounds=gap_rounds,
                fallback_taxonomy=args.gap_fallback_taxonomy,
            )

        # Phase B.5: per-camp session enumeration (Firecrawl-ready leaf URLs).
        # For "B" runs we enumerate after harvest. For "all", enumerate after Phase B
        # unless Phase C is explicitly enabled (phase_all_includes_c).
        if (
            run_phase == "B"
            and not dry_run
            and enumerate_sessions
            and town_filter
        ):
            _run_session_enumeration(town_filter[0], stats)

        if run_phase == "all":
            town_name = town_filter[0] if town_filter else None
            if (
                not dry_run
                and enumerate_sessions
                and town_filter
                and not SETTINGS.get("phase_all_includes_c")
            ):
                logging.info("Phase C skipped (phase_all_includes_c=false); running B.5")
                print("\nPHASE C skipped — proceeding to session enumeration (B.5)\n")
                _run_session_enumeration(
                    town_filter[0],
                    stats,
                    post_phases=True,
                    verify_all=args.verify_all,
                    verify_max_llm=args.verify_max_llm,
                    gap_rounds=gap_rounds,
                    max_searches=args.max_searches,
                    gap_fallback_taxonomy=args.gap_fallback_taxonomy,
                )
            elif SETTINGS.get("phase_all_includes_c"):
                current_count = count_camp_links()
                if current_count >= SETTINGS["target_count"]:
                    logging.info(
                        "PHASE_C skipped: target met (%d >= %d)",
                        current_count,
                        SETTINGS["target_count"],
                    )
                    print(
                        f"\nPHASE_C skipped: target met "
                        f"({current_count} >= {SETTINGS['target_count']})\n"
                    )
                    if not dry_run and enumerate_sessions and town_filter:
                        _run_session_enumeration(town_filter[0], stats)
                elif PHASE_C_KEYWORDS:
                    _run_discovery_phase(
                        "C",
                        PHASE_C_KEYWORDS,
                        stats,
                        dry_run,
                        args.limit,
                        seen_url_set,
                        town_filter,
                    )
                    if not dry_run:
                        stats.new_links_c += asyncio.run(
                            _harvest_candidates("C", stats, dry_run, town_name, host_filters)
                        )
                        stats.new_links_c += _process_direct_camp_candidates(
                            "C", stats, dry_run
                        )
                        if enumerate_sessions and town_filter:
                            _run_session_enumeration(town_filter[0], stats)
                    else:
                        asyncio.run(
                            _harvest_candidates("C", stats, dry_run, town_name, host_filters)
                        )
                else:
                    logging.info("PHASE_C skipped: no keywords configured (summer-only mode)")
                    if not dry_run and enumerate_sessions and town_filter:
                        _run_session_enumeration(town_filter[0], stats)
            else:
                logging.info("PHASE_C skipped: phase_all_includes_c disabled")

        elif run_phase == "C":
            if PHASE_C_KEYWORDS:
                town_name = town_filter[0] if town_filter else None
                _run_discovery_phase(
                    "C",
                    PHASE_C_KEYWORDS,
                    stats,
                    dry_run,
                    args.limit,
                    seen_url_set,
                    town_filter,
                )
                if not dry_run:
                    stats.new_links_c += asyncio.run(
                        _harvest_candidates("C", stats, dry_run, town_name, host_filters)
                    )
                    stats.new_links_c += _process_direct_camp_candidates(
                        "C", stats, dry_run
                    )
                    if enumerate_sessions and town_filter:
                        _run_session_enumeration(town_filter[0], stats)
                else:
                    asyncio.run(_harvest_candidates("C", stats, dry_run, town_name, host_filters))
            else:
                logging.info("PHASE_C skipped: no keywords configured")

        elif run_phase == "B" and dry_run:
            town_name = town_filter[0] if town_filter else None
            asyncio.run(_harvest_candidates(None, stats, dry_run, town_name, host_filters))

    except ConfigError as exc:
        logging.error("%s", exc)
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    if activity_path is not None and activity_path.exists():
        mirror_csv_to_txt(
            activity_path,
            title="Phase B harvest activity",
            description="Per-event audit log for crawls, LLM decisions, and saved links.",
        )

    print_summary(
        stats,
        town=town_filter[0] if town_filter else None,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()
