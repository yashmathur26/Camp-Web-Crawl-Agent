# AGENT BUILD SPEC — Camp Link Discovery Engine

SPEC_VERSION: 2.0
AUDIENCE: autonomous coding agent (Cursor). Execute top-to-bottom.
PROJECT_NAME: camp-link-engine
LANGUAGE: Python 3.11+
RUNTIME: local CLI, single entrypoint `python -m src.run`

---

## AGENT_OPERATING_RULES (read before writing any code)

1. Build in PHASE order (M0→M9). Complete and self-verify each milestone's `ACCEPTANCE` block before starting the next. Do not scaffold future milestones early.
2. After each milestone: run its acceptance check, then `git add -A && git commit -m "<milestone>"`.
3. Treat every `CONTRACT` (function signature + behavior) as fixed API. Other modules depend on these signatures; do not change them without updating all callers.
4. NEVER write secrets into source. Load from `.env` via `python-dotenv`. `.env` is gitignored.
5. NEVER hardcode state-specific data (`"MA"`, town names, keywords) outside `config/`. If you find yourself typing a town or state in `src/`, stop and move it to config.
6. The ONLY module that writes `data/camp_links.csv` is `src/store.py`. No other module touches the output file.
7. Default `SETTINGS["dry_run"] = True`. Discovery must spend $0 until a human flips it.
8. All network calls obey caps: `max_searches_per_run`, `max_pages_per_source`, `delay_seconds`, `crawl_concurrency`, `request_timeout`. No unbounded loops.
9. If a library method name in this spec mismatches the installed version, consult the installed package's docs/source and adapt — preserve the documented BEHAVIOR, fix the NAME.
10. When a step fails, consult `SECTION: FAILURE_MODES` before improvising. Apply the documented fix.

---

## SYSTEM_OVERVIEW

Pipeline: `DISCOVER (paid search) → CLASSIFY → HARVEST (free crawl) → FILTER → DEDUPE+STORE`.

Cost model: search calls cost money (per query); crawling is free (local headless browser). Therefore: spend searches to locate DENSE pages (directories), then crawl those for free. A directory page yields many camp links per single free crawl; never spend a paid search to locate one camp.

Output of THIS project: `data/camp_links.csv` — a deduplicated list of candidate camp URLs with provenance. Extraction of camp attributes (name/price/ages) is OUT OF SCOPE (separate downstream project).

Run sequencing (orchestrated in `src/run.py`):
- PHASE_A: small high-yield "find directories/lists" keyword set × towns → candidate pages.
- PHASE_B: crawl PHASE_A directory candidates (free) → camp links.
- GATE: if `count(camp_links.csv) >= SETTINGS["target_count"]` → SKIP PHASE_C (log it).
- PHASE_C: large activity-keyword set × towns → gap-fill; dedupe each result against `seen_urls` BEFORE store/crawl.

---

## FILE_TREE (build toward this)

```
camp-link-engine/
├─ .env                     # gitignored; API keys
├─ .gitignore
├─ requirements.txt
├─ README.md
├─ config/
│  ├─ settings.py           # SETTINGS dict, STATE
│  ├─ towns.py              # TOWNS: list[str]
│  └─ keywords.py           # PHASE_A_KEYWORDS, PHASE_C_KEYWORDS: list[str]
├─ src/
│  ├─ __init__.py
│  ├─ cache.py              # seen_searches + seen_urls persistence
│  ├─ urls.py               # normalize_url, to_absolute
│  ├─ discover.py           # search(query) provider-agnostic
│  ├─ classify.py           # classify(url)
│  ├─ crawl.py              # get_links_on_page, walk_site
│  ├─ filter_links.py       # is_likely_camp_link
│  ├─ store.py              # load_seen_urls, save_new_links  (ONLY writer of output)
│  └─ run.py                # orchestrator + CLI entrypoint
├─ cache/                   # gitignored
│  ├─ seen_searches.json
│  └─ seen_urls.json
├─ data/                    # gitignored
│  ├─ candidates.csv
│  └─ camp_links.csv
└─ logs/                    # gitignored
   └─ run_YYYY-MM-DD.log
```

---

## CONFIG_CONTRACTS

`config/settings.py`:
```python
STATE = "MA"
SETTINGS = {
    "search_provider": "serper",        # one of: serper|brave|serpapi|google_cse
    "cost_per_query_usd": 0.001,        # for dry-run estimate only
    "max_searches_per_run": 1000,       # HARD spend cap
    "max_pages_per_source": 300,
    "max_crawl_depth": 2,
    "stay_on_domain": True,
    "delay_seconds": 1.5,
    "crawl_concurrency": 3,             # semaphore size, keyed per host
    "request_timeout": 30,
    "results_per_search": 10,
    "user_agent": "FindFireflyBot/0.1 (+contact: you@email.com)",
    "respect_robots_txt": True,
    "target_count": 5000,
    "dry_run": True,
}
```
`config/towns.py`: `TOWNS: list[str]` (351 MA municipalities). Query builder appends `f", {STATE}"`.
`config/keywords.py`: `PHASE_A_KEYWORDS` (≈8–15 directory-finding terms), `PHASE_C_KEYWORDS` (≈100–200 activity/sport/instrument terms).

---

## DATA_CONTRACTS

`data/candidates.csv` columns:
`url, state, town, keyword, phase, classified_as, crawled, discovered_at`
- `phase` ∈ {A,C}; `classified_as` ∈ {directory,camp,unknown}; `crawled` ∈ {true,false}

`data/camp_links.csv` columns (OUTPUT; written only by `store.py`):
`url, state, town_hint, source_type, found_via, found_on_page, link_text, status, discovered_at`
- `source_type` ∈ {search,directory}; `status` ∈ {new,seen_before}

Cache files (`cache.py` owns):
- `seen_searches.json`: `{ "<normalized query>": "<iso ts>" }`
- `seen_urls.json`: array of normalized URL strings.

---

## MODULE_CONTRACTS (fixed signatures)

`src/urls.py`
```
normalize_url(url: str) -> str
# lowercase scheme+host; force https; strip leading "www."; remove trailing "/";
# drop query params matching ^(utm_|fbclid|gclid|mc_); drop #fragment; preserve path case.
to_absolute(base_url: str, href: str) -> str   # urljoin; return "" for non-http(s)/js/mailto/tel.
```

`src/cache.py`
```
load_seen_searches() -> dict[str,str]
record_search(query: str) -> None
is_search_seen(query: str) -> bool
load_seen_urls() -> set[str]            # normalized
add_seen_urls(urls: Iterable[str]) -> None
```

`src/discover.py`
```
search(query: str, limit: int) -> list[str]
# provider selected by SETTINGS["search_provider"]; returns result URLs (organic links).
# raises ConfigError on missing key; retries with exp backoff on 429/5xx; respects no global state.
```

`src/classify.py`
```
classify(url: str) -> Literal["directory","camp","unknown"]
# heuristic on host+path. directory hints: /camps,/programs,/directory,/activities,/recreation,
# guide/listicle hosts. crawl-free => treat "unknown" as crawlable (return "unknown", caller crawls).
```

`src/crawl.py`
```
async get_links_on_page(url: str) -> list[dict]      # [{"url": abs_url, "text": str}]
async walk_site(start_url: str, max_depth: int, max_pages: int) -> list[dict]
# on-domain BFS if stay_on_domain; visited set keyed by normalize_url; per-host semaphore =
# crawl_concurrency; delay_seconds between requests; request_timeout per page; skip+log errors;
# obey robots.txt if respect_robots_txt.
```

`src/filter_links.py`
```
is_likely_camp_link(url: str, text: str) -> bool
# KEEP if url/text matches: camp|program|class|clinic|session|academy|workshop|lessons
# DROP if: mailto:|tel:|^#|/login|/signin|/cart|/privacy|/terms|/about|/contact
# DROP host in DENY_DOMAINS = {facebook,instagram,twitter/x,linkedin,youtube,tiktok,
#   wikipedia,yelp,reddit,pinterest, *.gov press, news domains}. Bias toward KEEP on ambiguity.
```

`src/store.py`  (SOLE writer of `data/camp_links.csv`)
```
save_new_links(rows: list[dict], path="data/camp_links.csv") -> int
# normalize each row["url"]; skip if in load_seen_urls(); write header if file new;
# open(encoding="utf-8", newline=""); append unseen rows; add_seen_urls(...); return count added.
```

`src/run.py`
```
def main() -> None                      # CLI entry: orchestrate phases, caps, logging, summary.
# argparse flags: --dry-run/--no-dry-run (override SETTINGS), --phase {A,B,C,all}, --limit N.
```

---

## EXECUTION_PLAN (milestones with acceptance tests)

### M0 — SCAFFOLD
DO: create venv; `pip install crawl4ai python-dotenv tldextract`; install browser (`crawl4ai-setup`; fallback `python -m playwright install chromium`); write `.gitignore` (`.env`, `venv/`, `__pycache__/`, `data/`, `logs/`, `cache/`), `requirements.txt` (pinned), `README.md`, all `config/*` per CONFIG_CONTRACTS (towns/keywords may start partial), empty `src/__init__.py`; `git init`; commit.
ACCEPTANCE: `python -c "import crawl4ai, dotenv, tldextract"` exits 0; `config.settings.SETTINGS` importable; tree matches FILE_TREE.

### M1 — urls.py + cache.py
DO: implement `src/urls.py` and `src/cache.py` per MODULE_CONTRACTS.
ACCEPTANCE: unit asserts — `normalize_url("http://WWW.X.com/a/?utm_x=1#z") == "https://x.com/a"`; `normalize_url("https://x.com/a/") == "https://x.com/a"`; cache round-trips a query and a URL set across process restarts (JSON persisted).

### M2 — discover.py
DO: implement provider-agnostic `search()`; default provider `serper`; key from `.env`; exp backoff on 429/5xx; raise `ConfigError` if key missing.
ACCEPTANCE: with a valid key, `search("summer camps Lexington, MA", 10)` returns ≥1 http(s) URL; with key unset, raises `ConfigError` (no crash/stack-dump to user).

### M3 — discovery loop (PHASE_A) in run.py
DO: build queries `f"{kw} {town}, {STATE}"` for PHASE_A_KEYWORDS × TOWNS. If dry_run: print planned-query count + `count * cost_per_query_usd` estimate, make zero API calls. Else: skip `is_search_seen`; stop at `max_searches_per_run`; `record_search`; append unique results to `candidates.csv` (phase=A) deduped via `normalize_url`.
ACCEPTANCE: dry-run prints plan + cost, issues 0 network calls (verify by running with no key set — must not error in dry-run); real run (small `--limit`) writes candidates and re-run issues 0 duplicate queries (cache hit).

### M4 — crawl.py
DO: implement `get_links_on_page` then `walk_site` per contract (visited set, per-host semaphore, depth/page caps, delay, timeout, robots, error-skip, relative→absolute via `to_absolute`).
ACCEPTANCE: `get_links_on_page(<directory_url>)` returns ≥1 absolute-URL link dict; `walk_site` on a small directory respects `max_pages_per_source` (never exceeds) and terminates (no infinite loop) — assert visited count ≤ cap.

### M5 — classify.py + PHASE_B harvest
DO: implement `classify`; in run.py, for each candidate where `classified_as in {directory, unknown}` and `crawled == false`: `walk_site`, pass links through `is_likely_camp_link`, hand kept links to store (M6), set `crawled=true`.
ACCEPTANCE: harvesting PHASE_A candidates produces a non-trivial kept-link list; eyeball 20 kept links → majority are camp/program pages; no source loops beyond caps.

### M6 — filter_links.py + store.py
DO: implement both per contract. `store.save_new_links` is the only writer; idempotent.
ACCEPTANCE: first run writes N rows with header; immediate identical re-run returns 0 added and file row-count unchanged; manual check: no `mailto:`/social/denylisted hosts in output.

### M7 — GATE + PHASE_C
DO: after PHASE_B compute `count(camp_links.csv)`; if `>= target_count` skip PHASE_C (log "PHASE_C skipped: target met"). Else run discovery loop with PHASE_C_KEYWORDS (phase=C); for each result, dedupe against `load_seen_urls()` BEFORE store/crawl. Enforce `max_searches_per_run` across the FULL run (A+C combined).
ACCEPTANCE: with `target_count` set low, PHASE_C is skipped and logged; with it high, PHASE_C adds only URLs absent from seen_urls (assert no overlap with pre-C output).

### M8 — orchestration + logging + summary
DO: `main()` runs A→B→GATE→C under all caps; writes `logs/run_<date>.log`; prints end summary: searches_used, est_cost_usd, pages_crawled, new_links_per_phase, total_links, runtime_s, skipped_sources. argparse flags wired.
ACCEPTANCE: `python -m src.run --dry-run` prints plan+cost, 0 network calls; `python -m src.run --no-dry-run --limit 50` completes, writes log + summary, respects the 50 cap.

### M9 — portability audit + scheduling
DO: grep codebase for `"MA"`/town/keyword literals outside `config/`; report/fix. Provide OS-appropriate schedule instructions (cron/launchd/Task Scheduler) in README.
ACCEPTANCE: audit returns no state-specific literals in `src/`; changing `STATE`+`TOWNS`+keywords in `config/` is sufficient to retarget; README has schedule steps.

---

## FAILURE_MODES (diagnose here before improvising)

ENV/SETUP
- `Executable doesn't exist` / browser launch fail → run `crawl4ai-setup` or `python -m playwright install chromium`.
- `RuntimeError: event loop is already running` → entry must use `asyncio.run(main())`; do not build async crawl inside notebook/REPL.
- API key `None` → `load_dotenv()` not called or wrong var name; verify `.env`; raise `ConfigError`, don't stack-dump.

SEARCH
- HTTP 429 / quota → exp backoff + retry; honor `max_searches_per_run`; confirm provider plan; spread runs.
- Surprise cost → keep `dry_run=True` default; never bypass `max_searches_per_run`.
- Paying twice on rerun → must check `is_search_seen` before each call; `record_search` after.
- Town-name collision (Chelsea/Cambridge) → always append `, {STATE}`; use provider location bias if available.
- Junk result domains → enforce `DENY_DOMAINS` in `filter_links` before classify/crawl.

CRAWL
- Empty links on JS page → add wait/`wait_for`; if behind interaction, skip (v1).
- CAPTCHA/Cloudflare (aggregators) → mark blocked, skip, log; do not attempt bypass.
- robots disallow → skip + log.
- Relative URL stored → must `to_absolute` before store.
- Infinite crawl/trap (calendar, `?page=99999`, session ids) → `max_crawl_depth` + `max_pages_per_source` + visited(normalized) + skip absurd pagination.
- Hang/timeout/memory → per-page `request_timeout`, per-source page cap, bounded `crawl_concurrency` (semaphore PER HOST).
- Self IP-block → raise `delay_seconds`, lower concurrency, honest `user_agent`.
- Crawl4AI API name drift → check installed version's docs; preserve behavior.

DEDUPE/IO
- Duplicate explosion / www/https/slash/utm variants → `normalize_url` before all comparisons and before storing.
- CSV header missing / Windows blank rows / encoding → write header only if new; `open(encoding="utf-8", newline="")`.

LOGIC
- Concurrency hammering one host → semaphore keyed by host, not global only.
- PHASE_C re-finding A/B results → dedupe each C result vs `seen_urls` BEFORE store/crawl (the main C-efficiency rule).

---

## DONE_DEFINITION
- `python -m src.run --dry-run` prints plan + cost estimate, 0 network calls.
- Live run discovers + crawls locally under all caps; outputs deduplicated `data/camp_links.csv` with provenance.
- Re-run: 0 duplicate rows, 0 repeated paid searches (cache hits).
- Sequence A→B→GATE→C enforced; PHASE_C gated by `target_count`.
- Run log written; end summary printed.
- No state-specific literals outside `config/`.

## OUT_OF_SCOPE (do not build)
- Attribute extraction (name/price/ages) — downstream project, consumes `camp_links.csv`, uses local LLM (Ollama).
- Any write to Mom's Firefly app/DB. This project's only handoff is `camp_links.csv`.
