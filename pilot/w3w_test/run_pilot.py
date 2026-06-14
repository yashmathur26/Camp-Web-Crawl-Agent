#!/usr/bin/env python3
"""Isolated 3-town pilot: Waltham, Woburn, Watertown.

Runs Phase A → B → Engine v3 → Phase C gap-fill per town, then writes a
combined FINAL_sessions.csv + FINAL_sessions.txt under this folder.

Usage (from repo root):
  ./venv/bin/python pilot/w3w_test/run_pilot.py        # auto population-scaled budgets
  ./venv/bin/python pilot/w3w_test/run_pilot.py --gap-searches 40 --gap-rounds 1  # manual override

All outputs live under pilot/w3w_test/ — nothing touches data/lexington etc.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Repo root on sys.path before local imports
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

PILOT_ROOT = Path(__file__).resolve().parent
TOWNS = ["Waltham", "Woburn", "Watertown"]

FINAL_COLUMNS = [
    "town",
    "name",
    "register_url",
    "info_url",
    "dates",
    "ages",
    "price",
    "platform",
    "source_phase",
    "verdict",
]


def _setup_env() -> None:
    os.environ["FIREFLY_DATA_ROOT"] = str(PILOT_ROOT / "data")
    os.environ["FIREFLY_LOGS_ROOT"] = str(PILOT_ROOT / "logs")
    os.environ["FIREFLY_CACHE_ROOT"] = str(PILOT_ROOT / "cache")
    os.environ["FIREFLY_REGISTRY_DIR"] = str(PILOT_ROOT / "registry")
    # Cursor agent sandbox injects an empty PLAYWRIGHT_BROWSERS_PATH; always prefer
    # the user's real install when missing or pointing at cursor-sandbox-cache.
    pw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    real_pw = Path.home() / "Library" / "Caches" / "ms-playwright"
    if not pw or "cursor-sandbox-cache" in pw:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(real_pw)
    # Memory safety on 16GB (W3W crash fix): conservative profile + force Ollama
    # to keep ONE model and ONE worker (the Jetsam log showed 2x ~9GB workers).
    os.environ.setdefault("FIREFLY_RESOURCE_PROFILE", "16gb")
    os.environ.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
    os.environ.setdefault("OLLAMA_NUM_PARALLEL", "1")


_setup_env()


def town_is_complete(town: str) -> bool:
    """A town is done when its Phase C gap output exists (P0.5 resume)."""
    from src.data_layout import gap_new_sessions_csv

    try:
        return gap_new_sessions_csv(town).exists()
    except Exception:  # noqa: BLE001
        return False


def _init_dirs() -> None:
    for sub in ("data", "logs", "cache", "registry"):
        (PILOT_ROOT / sub).mkdir(parents=True, exist_ok=True)
    readme = PILOT_ROOT / "README.txt"
    if not readme.exists():
        readme.write_text(
            "W3W PILOT — Waltham, Woburn, Watertown\n"
            "=====================================\n\n"
            "Isolated test run. All pipeline artifacts are under:\n"
            "  data/<town>/phase_a|phase_b|engine|phase_gap/\n"
            "  registry/<town>.yaml\n"
            "  logs/pilot_run.log\n\n"
            "Final deliverables:\n"
            "  FINAL_sessions.csv\n"
            "  FINAL_sessions.txt\n"
            "  RUN_SUMMARY.json\n",
            encoding="utf-8",
        )


def _reset_pilot_state() -> None:
    """Fresh pilot — clear links, candidates, caches (not the README)."""
    import shutil

    for sub in ("data", "cache"):
        p = PILOT_ROOT / sub
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True)
    (PILOT_ROOT / "registry").mkdir(parents=True, exist_ok=True)
    # candidates + camp_links headers
    from src import data_layout
    from src.store import CAMP_LINKS_COLUMNS

    data_layout.candidates_csv().parent.mkdir(parents=True, exist_ok=True)
    with open(data_layout.candidates_csv(), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "url", "state", "town", "keyword", "phase", "classified_as",
                "crawled", "discovered_at", "title", "preferred",
            ],
        )
        w.writeheader()
    with open(data_layout.camp_links_csv(), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMP_LINKS_COLUMNS)
        w.writeheader()
    (PILOT_ROOT / "cache" / "seen_urls.json").write_text("[]", encoding="utf-8")
    (PILOT_ROOT / "cache" / "seen_searches.json").write_text("{}", encoding="utf-8")


_AGGREGATOR_HOSTS = frozenset({
    "activityhero.com", "bostontechmom.com", "mommypoppins.com", "teenlife.com",
    "reddit.com", "youtube.com", "facebook.com", "macaronikid.com",
})


def bootstrap_registry(
    town: str, state: str = "MA", *, max_providers: int = 0,
) -> Path:
    """Build engine registry YAML from Phase A/B camp_links for one town."""
    import yaml
    from engine.registry.proposer import _DENY_HOST_RE, fingerprint_vendor
    from src.data_layout import camp_links_csv

    links_path = camp_links_csv()
    by_host: dict[str, str] = {}
    host_counts: dict[str, int] = defaultdict(int)
    if links_path.exists():
        with open(links_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                hint = (row.get("town_hint") or "").strip()
                if hint and hint.lower() != town.lower():
                    continue
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                host = urlparse(url).netloc.lower().replace("www.", "")
                if not host or _DENY_HOST_RE.search(host) or host in _AGGREGATOR_HOSTS:
                    continue
                host_counts[host] += 1
                by_host.setdefault(host, url)

    if not by_host:
        from src.data_layout import candidates_csv

        cand_path = candidates_csv()
        if cand_path.exists():
            with open(cand_path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    if (row.get("town") or "").lower() != town.lower():
                        continue
                    if row.get("classified_as") not in ("camp", "provider", "rec_center"):
                        continue
                    url = (row.get("url") or "").strip()
                    host = urlparse(url).netloc.lower().replace("www.", "")
                    if host and not _DENY_HOST_RE.search(host):
                        by_host.setdefault(host, url)

    providers: list[dict] = []
    try:
        from engine.fetch.client import FetchClient

        fetch = FetchClient()
    except Exception:
        fetch = None

    ranked_hosts = sorted(
        by_host.keys(),
        key=lambda h: (-host_counts.get(h, 0), h),
    )
    if max_providers > 0:
        ranked_hosts = ranked_hosts[:max_providers]

    for host in ranked_hosts:
        seed = by_host[host]
        links: list[dict] = []
        if fetch:
            try:
                _text, links, _html = fetch.fetch_text(seed)
            except Exception:
                pass
        vendor, org_id, _ev = fingerprint_vendor(seed, links, host)
        name = host.split(".")[0].replace("-", " ").title()
        providers.append(
            {
                "name": name,
                "host": host,
                "seed": seed,
                "vendor": vendor,
                "org_id": org_id,
            }
        )

    reg_dir = PILOT_ROOT / "registry"
    reg_dir.mkdir(parents=True, exist_ok=True)
    out = reg_dir / f"{town.lower()}.yaml"

    if not providers:
        logging.warning("No providers discovered for %s — placeholder registry", town)
        payload = {"town": town, "state": state, "providers": [{
            "name": f"{town} Parks & Rec (search seed)",
            "host": f"{town.lower().replace(' ', '')}ma.gov",
            "seed": f"https://www.google.com/search?q={town}+MA+summer+camp+registration",
            "vendor": "unknown",
            "notes": "placeholder — re-run after Phase A/B finds real hosts",
        }]}
        out.write_text(yaml.dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return out

    payload = {"town": town, "state": state, "providers": providers}
    out.write_text(yaml.dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    logging.info("Registry %s: %d provider(s)", out.name, len(providers))
    return out


def _run_harvest(town: str, stats) -> int:
    from src.run import _harvest_candidates

    added = asyncio.run(
        _harvest_candidates("A", stats, dry_run=False, town_filter=town, host_filters=None)
    )
    logging.info("Phase B harvest for %s: +%d links", town, added)
    return added


def _run_discovery_and_harvest(town: str, stats, *, skip_phase_a: bool = False) -> None:
    from config.keywords import PHASE_A_KEYWORDS
    from src.cache import load_seen_urls
    from src.run import _run_discovery_phase

    town_filter = [town]
    if not skip_phase_a:
        seen = load_seen_urls()
        _run_discovery_phase(
            "A", PHASE_A_KEYWORDS, stats, dry_run=False, search_limit=None,
            seen_url_set=seen, towns=town_filter,
        )
    stats.new_links_b = _run_harvest(town, stats)


def _run_engine(town: str, *, fresh: bool = True) -> dict:
    from engine.run.runner import run_town
    from src.data_layout import DATA_ROOT

    counts = asyncio.run(
        run_town(town, out_root=DATA_ROOT, fresh=fresh, include_review=False)
    )
    logging.info("Engine %s: %s", town, counts)
    return counts or {}


def _run_phase_c(town: str, *, rounds: int, max_searches: int | None) -> dict:
    from src.agentic_gap import run_agentic_gap
    from src.engine_bridge import engine_sessions_for_town
    from src.search_budget import town_budget

    sessions = engine_sessions_for_town(town)
    if not sessions:
        logging.warning("Phase C skipped for %s — no engine sessions", town)
        return {"new_sessions": 0, "skipped": True}
    # Auto (default): population-scaled per-town ceiling. An explicit
    # --gap-searches N overrides it.
    if max_searches is None or max_searches < 0:
        max_searches = town_budget(town)["phase_c"]
        logging.info("Phase C %s: auto budget = %d searches/round", town, max_searches)
    return run_agentic_gap(
        town, rounds=rounds, max_searches=max_searches, sessions=sessions,
    )


def _read_engine_sessions(town: str) -> list[dict]:
    from src.data_layout import DATA_ROOT, town_slug

    path = DATA_ROOT / town_slug(town) / "engine" / "sessions.csv"
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "town": town,
                    "name": r.get("name", ""),
                    "register_url": r.get("register_url", ""),
                    "info_url": r.get("info_url", ""),
                    "dates": r.get("dates", ""),
                    "ages": r.get("ages", ""),
                    "price": r.get("price", ""),
                    "platform": r.get("extractor", "engine"),
                    "source_phase": "engine",
                    "verdict": r.get("verdict", ""),
                }
            )
    return rows


def _read_gap_sessions(town: str) -> list[dict]:
    from src.data_layout import gap_new_sessions_csv

    path = gap_new_sessions_csv(town)
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "town": town,
                    "name": r.get("name", ""),
                    "register_url": r.get("register_url", ""),
                    "info_url": r.get("info_url", ""),
                    "dates": r.get("dates", ""),
                    "ages": r.get("ages", ""),
                    "price": r.get("price", ""),
                    "platform": r.get("platform", "gap"),
                    "source_phase": "phase_c",
                    "verdict": r.get("parent_verdict", ""),
                }
            )
    return rows


def _merge_final(town_results: list[dict]) -> tuple[list[dict], dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    stats: dict = defaultdict(int)
    for block in town_results:
        town = block["town"]
        for row in block.get("engine_rows", []) + block.get("gap_rows", []):
            key = (town.lower(), (row.get("register_url") or row.get("info_url") or "").strip())
            if not key[1] or key in seen:
                continue
            seen.add(key)
            merged.append(row)
            stats[town] += 1
            stats["total"] += 1
    return merged, dict(stats)


def _write_final(rows: list[dict], summary: dict) -> tuple[Path, Path]:
    from src.csv_mirror import write_csv_bundle

    csv_path = PILOT_ROOT / "FINAL_sessions.csv"
    txt_path = PILOT_ROOT / "FINAL_sessions.txt"
    write_csv_bundle(
        csv_path,
        rows,
        FINAL_COLUMNS,
        title="W3W Pilot — Waltham, Woburn, Watertown — all sessions",
        description=(
            "Combined engine + Phase C gap-fill sessions from the isolated pilot run. "
            f"Total rows: {len(rows)}."
        ),
    )
    summary_path = PILOT_ROOT / "RUN_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return csv_path, txt_path


def _write_town_camp_lists(merged: list[dict], towns: list[str]) -> None:
    import importlib.util

    path = PILOT_ROOT / "write_camp_list.py"
    spec = importlib.util.spec_from_file_location("w3w_write_camp_list", path)
    if not spec or not spec.loader:
        logging.warning("Could not load write_camp_list.py — skipping readable lists")
        return
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from src.institution_output import write_institution_camps_txt

    for town in towns:
        town_rows = [r for r in merged if (r.get("town") or "").lower() == town.lower()]
        out = mod.write_readable_camp_list(town, town_rows)
        logging.info("Readable camp list → %s", out)
        print(f"Camp list ({town}): {out}")
        inst_out = PILOT_ROOT / "data" / town.lower() / f"{town.upper()}_INSTITUTION_CAMPS.txt"
        inst_out.parent.mkdir(parents=True, exist_ok=True)
        write_institution_camps_txt(town, town_rows, inst_out)
        logging.info("Institution camps → %s", inst_out)
        print(f"Institution camps ({town}): {inst_out}")


def run_town_pipeline(
    town: str,
    *,
    gap_rounds: int,
    gap_searches: int,
    skip_phase_a: bool = False,
    skip_phase_c: bool = False,
    max_registry_providers: int = 35,
) -> dict:
    from dotenv import load_dotenv
    from config.settings import SETTINGS
    from src.llm import unload_all_models
    from src.resource_guard import log_memory
    from src.run import RunStats

    load_dotenv(REPO / ".env")
    # P2.3: Phase B's LLM camp-page filter is the biggest crawl-time model load;
    # skip it during the pilot (the engine re-validates everything anyway).
    SETTINGS["ollama_validate_links"] = False
    SETTINGS["ollama_focus_verify"] = False

    stats = RunStats()
    t0 = time.monotonic()
    result: dict = {"town": town, "phases": {}}

    log_memory("town_start", town=town)
    if skip_phase_a:
        logging.info("========== %s: Phase B harvest only (skipping Phase A searches) ==========", town)
        stats.new_links_b = _run_harvest(town, stats)
        result["phases"]["ab"] = {"phase_a_skipped": True, "new_links_b": stats.new_links_b}
    else:
        logging.info("========== %s: Phase A + B ==========", town)
        _run_discovery_and_harvest(town, stats)
        result["phases"]["ab"] = {
            "searches": stats.searches_used,
            "new_links_b": stats.new_links_b,
        }
    unload_all_models()  # P1.2: free Ollama before the engine's render burst

    logging.info("========== %s: bootstrap registry ==========", town)
    reg = bootstrap_registry(town, max_providers=max_registry_providers)
    result["phases"]["registry"] = str(reg)

    logging.info("========== %s: Engine v3 ==========", town)
    eng = _run_engine(town, fresh=True)
    result["phases"]["engine"] = eng
    _shutdown_browsers()  # P1.1: close shared Chromium before Phase C's LLM load
    unload_all_models()

    if skip_phase_c:
        logging.info("========== %s: Phase C skipped (--skip-phase-c) ==========", town)
        result["phases"]["gap"] = {"skipped": True}
    else:
        logging.info("========== %s: Phase C gap-fill ==========", town)
        gap = _run_phase_c(town, rounds=gap_rounds, max_searches=gap_searches)
        result["phases"]["gap"] = {
            k: v for k, v in gap.items() if k != "rounds"
        }
    _shutdown_browsers()
    unload_all_models()
    log_memory("town_end", town=town)

    result["engine_rows"] = _read_engine_sessions(town)
    result["gap_rows"] = _read_gap_sessions(town)
    result["wall_clock_s"] = round(time.monotonic() - t0, 1)
    return result


def _shutdown_browsers() -> None:
    """Close the engine's shared Chromium between phases (P1.1)."""
    try:
        from engine.fetch.render import shutdown_browser_pool

        asyncio.run(shutdown_browser_pool())
    except Exception as exc:  # noqa: BLE001
        logging.debug("browser shutdown: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="W3W isolated 3-town pilot")
    parser.add_argument("--gap-rounds", type=int, default=1)
    parser.add_argument("--gap-searches", type=int, default=-1,
                        help="Max gap searches per round per town "
                             "(default: auto, population-scaled per town; pass N to override)")
    parser.add_argument("--no-reset", action="store_true",
                        help="Keep existing pilot data (resume-ish)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip towns whose Phase C output already exists")
    parser.add_argument("--towns", default="",
                        help="Comma-separated towns (default: all three)")
    parser.add_argument("--skip-phase-a", action="store_true",
                        help="Skip discovery/harvest; use existing camp_links")
    parser.add_argument("--skip-phase-c", action="store_true",
                        help="Skip gap-fill (keep existing phase_gap output)")
    parser.add_argument("--max-registry-providers", type=int, default=35,
                        help="Cap auto-registry size (0 = no cap)")
    args = parser.parse_args()

    _setup_env()
    _init_dirs()
    if not args.no_reset:
        _reset_pilot_state()

    log_file = PILOT_ROOT / "logs" / "pilot_run.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    from config.settings import SETTINGS

    SETTINGS["dry_run"] = False

    town_list = (
        [t.strip() for t in args.towns.split(",") if t.strip()]
        if args.towns else list(TOWNS)
    )
    started = datetime.now(timezone.utc).isoformat()
    logging.info("W3W pilot starting — towns: %s", ", ".join(town_list))
    logging.info("Pilot root: %s", PILOT_ROOT)
    logging.info(
        "Playwright browsers: %s",
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "(default)"),
    )

    town_results: list[dict] = []
    per_town_summary: dict = {}
    t0 = time.monotonic()

    from src.resource_guard import MemoryBudgetError

    for town in town_list:
        if args.resume and town_is_complete(town) and not args.skip_phase_c:
            logging.info("Skipping %s — Phase C already complete (resume)", town)
            per_town_summary[town] = {"status": "skipped_complete"}
            block = {"town": town, "engine_rows": _read_engine_sessions(town),
                     "gap_rows": _read_gap_sessions(town)}
            town_results.append(block)
            continue
        try:
            block = run_town_pipeline(
                town,
                gap_rounds=args.gap_rounds,
                gap_searches=args.gap_searches,
                skip_phase_a=args.skip_phase_a,
                skip_phase_c=args.skip_phase_c,
                max_registry_providers=args.max_registry_providers,
            )
            town_results.append(block)
            per_town_summary[town] = {
                "engine_sessions": len(block["engine_rows"]),
                "gap_sessions": len(block["gap_rows"]),
                "phases": block["phases"],
                "wall_clock_s": block["wall_clock_s"],
            }
        except MemoryBudgetError as exc:
            # Low memory — stop cleanly, keep what's done, write partial summary.
            logging.error("Town %s deferred: %s", town, exc)
            per_town_summary[town] = {"status": "deferred_low_memory", "error": str(exc)}
            break
        except Exception as exc:
            logging.exception("Town %s failed: %s", town, exc)
            per_town_summary[town] = {"error": str(exc)}

    merged, merge_stats = _merge_final(town_results)
    csv_path = PILOT_ROOT / "FINAL_sessions.csv"
    txt_path = PILOT_ROOT / "FINAL_sessions.txt"
    csv_path, txt_path = _write_final(merged, {
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "towns": town_list,
        "total_wall_clock_s": round(time.monotonic() - t0, 1),
        "per_town": per_town_summary,
        "merged_row_counts": merge_stats,
        "final_csv": str(csv_path),
        "final_txt": str(txt_path),
    })

    _write_town_camp_lists(merged, town_list)

    logging.info("DONE — %d merged rows → %s", len(merged), csv_path)
    print(f"\n=== W3W PILOT COMPLETE ===")
    print(f"FINAL CSV: {csv_path}")
    print(f"FINAL TXT: {txt_path}")
    print(f"Rows: {len(merged)}")
    print(f"Log: {log_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
