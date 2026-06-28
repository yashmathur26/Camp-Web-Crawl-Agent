# implementation_plan.md — Engine v3 Technical Design

Design reference for the coding agent. Pair with `roadmap.md` (sequencing), `task.md`
(work units), `rules.md` (constraints — read it first; it overrides this document).

---

## 1. Problem statement (why the old engine is replaced, not refactored)

The old pipeline (`src/`) is a generic web crawler: fetch pages, guess each page's "role,"
scrape link text, keyword-filter names, tie-break with an LLM. Production evidence shows
this is the wrong primitive:

- The ONE vendor with a structured adapter (WebTrac) produced 40 clean, dated,
  parent-ready sessions. Every vendor handled generically (MyRec, ACTIVE, Sawyer,
  CampBrain, enrollsy, Squarespace, custom JS) returned 0–600-char shells and ~zero yield.
- Filtering ran on name strings BEFORE extraction, so JS-shell chrome ("Referral", "")
  and keyword-less real programs (Super Soccer Stars, Kidcreate, Quickball) were dropped
  by design.
- The LLM was trusted on unanswerable inputs (a 0-char page classified as "a catalog
  listing camps with names, ages, dates"; `name=Badminton` adjudicated with no context)
  and failed CLOSED when it should fail open.
- Fetching used `networkidle` (hangs up to 6m43s per 171-char shell), 3× timeout retries,
  no cross-provider cache, and followed PDFs/PNGs as pages.
- Three competing verdict systems (inline signals, Phase P, Phase Q) plus a separate
  fabrication gate produced contradictory output ("0 published" and "+26 rows" for the
  same provider in the same log).
- Plans were marked complete without behavior changing because no eval existed.

The replacement reframes the problem: **camp registration in this market runs on a small
set of SaaS vendors. The product is ~10–15 vendor integrations + a thin curated registry
+ one careful generic fallback + one gate + one eval.** Towns don't transfer; vendors do.

## 2. Product contract

For any input town, produce four CSVs. The primary product value is **`info_url`: the
content-rich page right before registration** — the page the downstream Firecrawl stage
will mine for taxonomy/vector analysis. Groups/providers are listed once; every individual
camp under them gets its own row.

```
providers.csv  provider_id, name, host, town, platform, platform_org_id, seed_url, status
programs.csv   program_id, provider_id, name, info_url, category_hint, description_snippet
sessions.csv   session_id, program_id, name, info_url, register_url, dates, ages, price,
               verdict, evidence_json, extractor, fetched_at, content_chars
gaps.csv       provider_id, reason(needs_adapter|render_failed|blocked|empty|needs_review),
               evidence, suggested_action
```

**Info-url invariant (R4.3):** publish only if this run fetched info_url and stored ≥400
chars of rendered text containing the program name; record `content_chars`.

**Verdicts:** `parent_ready` (register page confirmed via enrollment signals),
`info_confirmed` (info page proven; register not confirmed — PUBLISHABLE), `gap:*`.
This deliberately fixes the old MyRec paradox where 26 real camps published zero because
empty detail *shells* failed an evidence rule.

**Program vs Session:** identical-name rows differing only by date window collapse into
one Program with N Sessions (Hayden's 10 "Lower Camp" weeks = 1 program / 10 sessions).
Grouping key: `(provider_id, normalized_name)`; normalization strips dates, week labels,
session numbers.

## 3. Package layout

```
engine/
  model.py              dataclasses + IDs + provenance + (de)serialization
  registry/
    schema.py           registry + proposals YAML formats, loader, validator
    towns/<town>.yaml   curated provider registry (source of truth per town)
    proposer.py         (Phase 6) discovery → proposals
  fetch/
    client.py           fetch_text(url) plain path; budgets; logging
    render.py           fetch_rendered(url) Playwright path; fixed-wait; 20s cap; 1 try
    cache.py            normalize_url-keyed; memory + sqlite/disk persistence
  extract/
    base.py             Extractor ABC (see §5)
    vendors/{webtrac,myrec,active,sawyer,campbrain,enrollsy,daxko,
             communityed,recdesk,civicrec}.py
    generic.py          long-tail path (see §7)
    llm.py              extraction-only LLM wrapper enforcing R3
  validate/
    gate.py             the ONE gate; returns Published|Gap result objects
    signals.py          ported enrollment_signals regex core
  run/
    runner.py           per-provider jobs, parallel (Phase 7), resumable, checkpoint
    report.py           four CSVs + narration log + run summary + eval table
  eval/
    ground_truth/<town>.csv
    score.py            recall/precision/info-validity; writes eval/history/<ts>.json
config_engine.py        ≤15 documented knobs
tools/check_imports.py  CI: fail on `import src` inside engine/
```

## 4. Registry (the input)

```yaml
# engine/registry/towns/lexington.yaml
town: Lexington
state: MA
providers:
  - name: J.W. Hayden Recreation Centre
    host: jwhayden.org
    seed: https://www.jwhayden.org/summer-camp
    vendor: webtrac
    org_id: majwhaydenweb            # the myvscloud subdomain
  - name: LexRec (Town of Lexington)
    host: lexrecma.myrec.com
    seed: https://lexrecma.myrec.com/info/activities/activities.aspx
    vendor: myrec
    org_id: lexrecma
    aliases: [lexingtonma.gov]       # funnel dedupe: gov site resolves here (R5/old §3.4)
  - name: Munroe Center for the Arts
    host: munroecenter.org
    seed: https://munroecenter.org/summer-camp.html
    vendor: active
    org_id: TheMunroeCenterfortheArts
  - name: Lexington Farm (LexFarm)
    host: lexfarm.org
    seed: https://lexfarm.org/education
    vendor: unknown                  # → generic path
```

Notes:
- `aliases` implements funnel dedupe at the data level: two old "providers" that share a
  backend become one registry entry; the engine enumerates once, attributes to all.
- `vendor: unknown` is legal and routes to `extract/generic.py`.
- Seed list for lexington.yaml comes from `scripts/fingerprint_providers.py` PROVIDERS.

## 5. Extractor interface

```python
class Extractor(ABC):
    vendor: str
    @abstractmethod
    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        """Return programs+sessions with candidate info_urls, or a diagnosed gap.
        Must not publish; the gate does that. Must not call the LLM unless it is
        generic.py. Must prefer the vendor's data path over rendering (R5.7)."""

@dataclass
class ExtractResult:
    programs: list[Program]          # sessions nested under programs
    gap: Gap | None                  # set when the provider yielded nothing usable
    fetch_log: list[FetchRecord]
```

Dispatch in runner: `vendor in VENDORS → vendors[vendor]`, else `generic`. An extractor
returning zero programs MUST return a Gap with a reason — empty-and-silent is illegal (R4.4).

## 6. Vendor extractor specs (wave 1 + 2)

### webtrac (port)
- Source of truth: catalog search `{org}.myvscloud.com/webtrac/web/search.html?module=AR&type=CAMP`,
  server-rendered. Item pages (`iteminfo.html?FMID=…`) are content-rich (1.7–2.5 KB) →
  they are the info_urls and usually verify `parent_ready` via signals.
- Port from `src/platforms.py::adapter_webtrac`; add Program grouping per §2.
- Camp-scoped catalog → skip topical filtering (R4.2).

### myrec (rewrite — do NOT port the old behavior)
- The catalog listings (`/info/activities/default.aspx?type=camps`, `type=activities`)
  are server-rendered rows carrying name + ProgramID + often dates; the detail pages
  (`program_details.aspx?ProgramID=…`) are 171-char JS shells.
- Extract name/ProgramID/dates/ages from listing rows ONLY. Never fetch detail shells in
  bulk (old cost: ~25 wasted minutes/town).
- info_url decision (one-time spike): render ONE detail page via `fetch/render.py`; if it
  yields ≥400 chars, detail pages are info_urls (rendered per-publish to satisfy the
  invariant, cached); else use the catalog page anchor as info_url. Encode the decision
  in code comments + a fixture.
- Expected verdicts: mostly `info_confirmed`.

### active (new)
- `campscui.active.com/orgs/{org}?season={id}` is a SPA; its session data loads from a
  JSON endpoint (inspect the org page's XHR — catalog/listing API keyed by org + season).
- Extractor: resolve org_id (registry) and season id (registry or scrape the provider's
  marketing page link, as Munroe's `?season=3743834` shows), call the API, map sessions.
- info_url: the per-session ACTIVE detail URL if it renders content; else the provider's
  own per-camp page found on the marketing site; else org page + anchor.
- Save the raw API JSON as `tests/fixtures/active/munroe.json`.

### sawyer
- `hisawyer.com/{org}/schedules/activity-set/{id}` pages embed a JSON payload with the
  full activity data (old fixtures exist, 4.4–4.9 KB). Parse the embedded JSON; do not
  scrape the DOM. activity-set page = info_url.

### campbrain
- `{org}.campbrainregistration.com` sits behind a queue-it throttle (Summers Edge fetched
  368 chars with a `queueittoken`). Try rendered fetch with realistic UA + cookie jar;
  if still throttled → `gap: blocked` with evidence. The provider's own marketing site
  may still yield programs via the generic path; run both and merge.

### enrollsy
- `app.enrollsy.com/enroll/{org}` is a SPA (574 chars static). Inspect for a JSON config/
  classes endpoint; if none reachable, rendered fetch; else `gap: render_failed`.

### daxko
- `operations.daxko.com/Online/{site}/ProgramsV2/…` listing links carry program names
  (old `_extract_daxko_sessions` logic is a usable starting point — port the test too).

### communityed (WooCommerce variant — rewrite)
- The class grid (`/lexplorations/find-a-class`) is client-rendered: static page 1 and
  page 2 returned byte-identical 5,801 chars — static pagination is fake. Paginate via
  `fetch/render.py`.
- Products live at `/{prefix}/class/{slug}` and ARE the info pages (content-rich,
  ~1.4 KB+ with name/dates/price). Scope to the seed's catalog prefix; never touch
  `/shop/` root. Cap categories × pages.
- Week-category link TEXT on the landing page carries dates ("Week One: June 29 – July 2")
  — harvest as session evidence.
- Target: the full ~60–70 Lexplorations camps (ground truth will say exactly).

### recdesk / civicrec / communitypass / ultracamp
- Stubs registering detection + `gap: needs_adapter` until R8.1 admits them.

## 7. Generic long-tail path (`extract/generic.py`)

For `vendor: unknown` — custom WordPress, Squarespace, Wix, hand-made sites:

1. `fetch_rendered(seed)`. If < 400 chars → `gap: empty` (with the render attempted —
   distinguishes `empty` from `render_failed`).
2. Deterministic harvest first: JSON-LD/schema.org events, heading+link clusters,
   repeated card patterns. Port `crawl_link_score` for follow ranking.
3. Bounded follow: same-host, depth ≤ 2, top-K scored links, media classes refused,
   provider wall-clock budget.
4. LLM extraction (R3): input = rendered text (≥400 chars), output = JSON program records
   `{name, dates?, ages?, price?, info_url_candidate}`. JSON-repair + one retry;
   unparseable → keep raw harvest + `needs_review` flag (fail open).
5. Candidate info_url per program: the page where the record was extracted, unless a
   better same-host per-camp page was found.
6. Gate decides. Programs without sufficient evidence publish as `needs_review` only if
   the info-url invariant holds; otherwise gap.

## 8. The gate (`validate/gate.py`)

Single entry: `gate(program_or_session, fetch) -> Published | Gap`.

Checks, in order:
1. Name integrity: not chrome/menu text, not a filename, not a bare ID, not empty
   (port + extend the old CHROME_LABELS idea).
2. Info-url invariant: fetched this run, ≥400 chars, contains normalized program name
   (fuzzy ≥ token-set match). Record `content_chars`.
3. Evidence: at least one of {summer-window dates, youth age/grade, camp-scoped catalog
   provenance}. Adult/senior/membership/league/fundraiser evidence → gap with reason
   (port the old hard-drop regexes as evidence rules, applied to EXTRACTED fields,
   not raw names).
4. Register verification (optional upgrade): if register_url present, run ported
   enrollment signals → may upgrade verdict to `parent_ready`. Failure here NEVER blocks
   publishing an `info_confirmed` row.
5. Geo: out-of-state host/register → gap (port `is_out_of_state_url`).

One writer (`run/report.py`) consumes gate results; logs, CSVs, and summaries all read
the same result list (R6.1).

## 9. Fetch layer details

- `fetch_text(url)`: httpx, UA from config, robots respected, politeness delay per host,
  cache check first, timeout ~25s, retry ×1 on connection error only.
- `fetch_rendered(url)`: Playwright (chromium, headless), `domcontentloaded` + settle
  loop (poll DOM length until stable for 1.5s) with hard cap 20s, single attempt,
  returns (text, links, html). Browser pool capped (2).
- `cache.py`: key = `normalize_url(url)` (ported); value = (text, links, status, ts);
  memory dict + sqlite at `data/cache/fetch_cache.db`; per-run namespace + optional TTL
  for cross-run reuse.
- Budgets: `provider_budget_s` (default 120) checked between fetches; exceeding →
  extractor returns partial result + `gap: budget_exceeded` note in evidence.

## 10. LLM wrapper (`extract/llm.py`)

- One function: `extract_programs(page_text, url, town) -> list[dict] | None`.
- Enforces R3 mechanically: raises if `len(page_text) < 400`; no other call sites exist.
- Ollama local (port the old `chat()` HTTP plumbing, drop the purpose-routing sprawl);
  temperature 0, `format=json`, JSON-repair pass, one retry, then None (caller fails open).
- Logs purpose/model/input-size/raw/parsed via the narration logger.

## 11. Eval (`eval/score.py`)

- Ground truth CSV: `provider, program_name, session_dates(optional), true_info_url`.
- Matching: provider by host; program by normalized-name fuzzy match (token set ratio
  ≥ 0.85); session by program + overlapping date window.
- Metrics: program recall, session recall (where GT has sessions), precision
  (published rows matching GT or manually whitelisted), info-url validity (live fetch).
- Output: console table + `eval/history/<timestamp>.json`. `--compare` flag diffs two
  history entries. CI smoke mode runs offline against fixtures.

## 12. Runner & report

- v0 (Phase 1): sequential, registry → extractor → gate → writer.
- Phase 7: asyncio task per provider, host-aware politeness, resumable via
  `data/<town>/engine/checkpoint.json` (provider_id → done + result hash), narration log
  per provider, summary = eval table + gaps table + per-provider timings.

## 13. Config (`config_engine.py`) — the complete knob list

```python
ENGINE = {
  "user_agent": "...",                 # realistic browser UA (gov sites 403 bot UAs)
  "min_info_chars": 400,               # R4.3 invariant
  "render_cap_s": 20,                  # R5.2
  "fetch_timeout_s": 25,
  "provider_budget_s": 120,            # R5.4
  "politeness_delay_s": 1.0,
  "max_browsers": 2,
  "generic_max_depth": 2,
  "generic_max_follows": 12,
  "ollama_base_url": "http://localhost:11434",
  "ollama_model": "llama3.2",          # extraction only (R3)
  "cache_ttl_h": 24,
  "concurrency": 4,                    # Phase 7 only
}
```
Adding a knob requires a comment naming the concrete failure it addresses (R6.3).

## 14. Salvage map (authoritative)

| Old asset | Fate |
|---|---|
| `adapter_webtrac`, `_extract_daxko_sessions` | PORT |
| `enrollment_signals.py` regex core | PORT → `validate/signals.py` |
| `normalize_url`, `crawl_link_score`, geo filter, Phase A denylists | PORT (latter in Phase 6) |
| `scripts/fingerprint_providers.py` PROVIDERS + signatures | PORT → registry + proposer |
| `tests/fixtures/**` | REUSE; add active/sawyer/enrollsy fixtures |
| navigator(s), role classifier, name filter (`relevance.py`), LLM tie-breaker, link-follow gate | DELETE (replaced per §§5–8) |
| `session_quality.py` + `parent_verify.py` + fabrication gate | MERGE→DELETE into `gate.py` |
| crawl tier profiles + ~45 settings knobs | DELETE |
| characterization tests asserting broken output | DELETE; replace with contract tests |

## 15. Testing strategy

- Every vendor extractor: offline fixture test (captured real response) + a Program-
  grouping assertion.
- Gate: table-driven tests over the §8 checks, including the chrome-name, empty-page,
  PDF, adult-program, and out-of-state cases that produced the old junk rows.
- Fetch: cap/cache/refusal tests with a local stub server.
- Eval smoke in CI (offline, fixtures); full eval run manually per phase exit.
- Parity guard during transition: engine output must be a superset of the old pipeline's
  parent_ready rows for Lexington (never lose what worked).
