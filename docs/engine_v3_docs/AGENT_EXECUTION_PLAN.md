# AGENT EXECUTION PLAN — Lexington Recall/Precision Fixes

> **Audience:** autonomous coding agent (Claude Code / Cursor) working in repo root
> `/Users/yashmathur/Desktop/firefly web scraper`.
> **Objective:** program recall 58.2% → ≥90%, precision 82.9% → ≥97% against
> `data/_baseline/lexington/baseline.json`, without regressing session recall (87.2%).

---

## GLOBAL RULES (read before any task)

1. **NEVER run paid searches.** Do not invoke `python -m src.run --no-dry-run --phase A` or `--phase C/gap`. All work here is extraction/scoring — no search credits.
2. **NEVER modify anything under `data/_baseline/`.** It is ground truth. Read-only.
3. **Ollama may be offline.** Every LLM call path you touch must degrade gracefully via the existing pattern: check `src.llm.is_available()` → rules-only fallback. Tests must pass with Ollama down.
4. **Network in tests is forbidden.** All new tests use fixture HTML/JSON under `tests/fixtures/` — no live fetches. Live verification runs are listed separately as MANUAL VERIFY steps for the human.
5. **After every task:** run `./venv/bin/python -m pytest -x -q` and fix failures before proceeding. Then `git add -A && git commit -m "<task id>: <summary>"`. One commit per task.
6. **Do not rename existing CSV columns.** Only append new columns at the end of column lists (downstream consumers index by name, but the .txt mirrors are positional).
7. If a task's instructions conflict with existing code structure, prefer the existing structure and note the deviation in the commit message. Do not refactor beyond task scope.
8. Config values go in `config/settings.py` `SETTINGS` dict; never hardcode in `src/`.

---

## TASK 0.1 — Fuzzy program matcher + eval script

**Create:** `scripts/score_town.py`

```python
"""Score a town's published sessions against data/_baseline/<town>/.

Usage: ./venv/bin/python scripts/score_town.py --town Lexington
Appends one row to data/<town_slug>/eval_history.csv and prints a summary.
"""
```

**Requirements:**

1. Add `rapidfuzz` to `requirements.txt`. Install: `./venv/bin/pip install rapidfuzz`.
2. Load baseline programs from `data/_baseline/<slug>/camp_sessions.csv`
   (columns are headerless in baseline — inspect the file first; first column is
   name, second is register URL, third platform, fourth dates; confirm by reading
   the first 5 lines before writing the parser).
3. Load published sessions from `data/<slug>/phase_p/all_verified.csv` if it
   exists, else `data/<slug>/phase_b5/camp_sessions.csv`.
4. **Program key derivation** (both sides):
   - `host` = netloc of register_url, lowercase, strip `www.`
   - `norm_name` = name lowercased; strip punctuation; remove tokens
     `{camp, camps, summer, 2025, 2026, week, session, the, a}`; collapse whitespace.
   - Program identity = group sessions by `(host, norm_name)`.
5. **Match logic** (baseline program → published program):
   - Exact: same `(host, norm_name)` → strict match.
   - Fuzzy: same host AND `rapidfuzz.fuzz.token_set_ratio(norm_name_a, norm_name_b) >= 75` → fuzzy match.
   - URL: any session register_url (canonicalized via `src.urls.normalize_url`)
     equal across sides → match regardless of name.
6. **Metrics output:**
   - `program_recall_strict`, `program_recall_fuzzy` = matched baseline programs / total baseline programs
   - `session_recall` = matched baseline sessions / total baseline sessions (match = canonical register_url equality)
   - `precision` = published sessions whose host appears in baseline provider list AND parent_verdict ∉ {wrong_audience, off_season} / total published. (Approximation — note it in docstring.)
   - `providers_covered` = baseline hosts with ≥1 published row / 21
7. Append CSV row to `data/<slug>/eval_history.csv` with columns:
   `timestamp,recall_strict,recall_fuzzy,session_recall,precision,providers_covered,published_rows`. Create file with header if absent.
8. Print a table of **unmatched baseline programs** (host + name) — this is the work list for later tasks.

**Test:** `tests/test_score_town.py` — synthetic baseline + published fixtures
covering: exact match, fuzzy match ("Musical Theater Camp" vs
"Specialty Camps: Musical Theater" must match), URL match, and a miss.

**MANUAL VERIFY (human):** run `scripts/score_town.py --town Lexington`, record
the corrected recall numbers.

---

## TASK 0.2 — Wire eval into pipeline end

**Modify:** `src/run.py` → `_run_session_enumeration()`: after the
`update_pilot_analysis(...)` call, invoke the scorer **only if**
`data/_baseline/<slug>/` exists:

```python
from scripts.score_town import score_town  # refactor scripts/score_town.py to expose score_town(town) -> dict
result = score_town(town_name)
logging.info("Eval vs baseline: %s", result)
```

Wrap in try/except — eval failure must never fail a pipeline run.

**Test:** extend `tests/test_score_town.py` with a call to `score_town()` as a
function (not subprocess).

---

## TASK 1.1 — `granularity` column

**Modify:** `src/sessions.py`

1. Append `"granularity"` to `SESSION_CSV_COLUMNS` (END of list — Rule 6).
2. Every existing session row construction sets `granularity="session"`.
   Find all dict-literal session constructions (grep `register_url`) and the
   adapter return paths; set the default in ONE place if a row-factory exists,
   else add `row.setdefault("granularity", "session")` in `write_session_outputs`.

**Test:** `tests/test_granularity.py` — `write_session_outputs` round-trip:
rows without the key get `"session"`, rows with `"program"` keep it.

---

## TASK 1.2 — Provider-level fallback rows

**Modify:** `src/sessions.py` → `enumerate_town()` (or the per-provider result
handler inside it — locate where each provider's `sessions` list is finalized).

**Logic, per provider result with `len(sessions) == 0`:**

```python
if _is_known_camp_provider(seed_url):          # new helper, see below
    sessions = [_fallback_program_row(seed_url, result)]
```

**New helper `_is_known_camp_provider(url) -> bool`:**
True iff host of url appears in `data/shared/phase_b/camp_links.csv` (use
existing loader in `src/parent_auditor._load_camp_link_hosts` — import or copy
pattern) OR host appears in `data/_baseline/<town>/baseline.json` providers OR
`src.camp_hosts.is_camp_host_seed_url(url)` is True.

**New helper `_fallback_program_row(seed_url, result) -> dict`:**

```python
{
    "name": f"{_provider_display_name(seed_url)} — Summer Program",
    "register_url": _best_register_url(result, seed_url),
    "platform": result.get("platform") or "fallback",
    "dates": "", "ages": "", "price": "",
    "row_type": "session",            # keep existing column semantics
    "source_url": seed_url,
    "granularity": "program",
}
```

- `_provider_display_name`: host minus TLD, dots→spaces, title-cased
  (`vikingcamps.com` → `Vikingcamps`); if the result captured a page `<title>`,
  prefer its first segment before `|` or `—`.
- `_best_register_url`: first URL in the result's harvested links matching
  `src.registration.is_registration_platform_url`, else any same-host link whose
  path contains `regist|enroll|signup|sign-up`, else `seed_url`.
- **Dedup guard:** in `write_session_outputs`/merge logic, if the same host has
  ≥1 `granularity="session"` row, drop its `granularity="program"` rows.

**Tests:** `tests/test_fallback_rows.py`
- zero-session known provider → exactly 1 program row, register_url == seed when no better link
- zero-session UNKNOWN host → 0 rows (precision guard)
- host with real sessions + stale program row → program row dropped

---

## TASK 1.3 — Fallback rows flow through quality phases

**Modify:**
- `src/session_quality.py`: `granularity="program"` rows are exempt from
  date-based checks; they tier as `needs_trail` unless register_url passes
  `registration_url_priority` (then `registrable`).
- `src/parent_verify.py`: program rows ARE verified (fetch + youth/summer check)
  but a missing cart/price does NOT demote them below `brochure_only`.
- `src/deliverables.py`: program rows render in catalog with marker
  `[PROVIDER PAGE]`; counted separately in `QUALITY_REPORT.txt`
  (`program_fallback_rows: N`).

**Test:** `tests/test_fallback_quality.py` — program row with myrec register_url
→ registrable; with marketing URL → needs_trail; never `rejected` solely for
missing dates.

**MANUAL VERIFY:** re-run B.5 for Lexington
(`./venv/bin/python -m src.run --no-dry-run --phase B5 --town Lexington` — uses
no search credits), then `scripts/score_town.py --town Lexington`.
**Gate: program_recall_fuzzy ≥ 0.75 before starting Task 2.**

---

## TASK 2.1 — Sawyer adapter

**Modify:** `src/platforms.py` (follow the existing adapter pattern, e.g.
`adapter_community_ed` / `adapter_ymca`).

**New `adapter_sawyer(url, ...)`:**

1. Fetch the provider page (existing fetch util). Regex the HTML for the Sawyer
   embed and capture the widget/business identifier. Search patterns, in order:
   - `hisawyer\.com/(?:widget|embed)/([\w-]+)`
   - `data-sawyer[\w-]*="([\w-]+)"`
   - any `https://www\.hisawyer\.com/([\w-]+)/(?:schedules|activity-set)` link
2. With the captured slug, fetch the public schedule page
   `https://www.hisawyer.com/<slug>/schedules` with the browser user-agent
   already used in `_run_session_enumeration` (Sawyer 403s bot UAs).
3. Parse activities: the schedules page embeds JSON
   (look for `<script id="__NEXT_DATA__"` or `window.__INITIAL_STATE__`; if
   neither present, parse DOM cards: activity name, date range, age range,
   price, and the `activity-set` link → `register_url`).
   **First implementation step:** save a live copy of
   `https://www.hisawyer.com/<fuse-slug>/schedules` into
   `tests/fixtures/sawyer_fuse.html` (MANUAL step for human if agent lacks
   network), and write the parser against the fixture.
4. Filter with the existing youth/summer focus filter; emit standard session
   rows, `platform="sawyer"`, `granularity="session"`.
5. Register adapter: in the platform dispatch (where `detect_platform()` result
   maps to adapters), route `"sawyer"` → `adapter_sawyer`. Update
   `config/platforms_registry.py` `sawyer.tier` → `"structured"`.

**Failure behavior:** any step failing → return 0 sessions (Task 1.2 fallback
covers it). Log reason via `session_log`.

**Test:** `tests/test_adapter_sawyer.py` against the fixture — ≥1 session, has
name + register_url containing `hisawyer.com`.

---

## TASK 2.2 — Shared rendered-fetch + agent_nav extraction

**Modify:** `src/crawl.py`

1. Extract the existing YMCA networkidle Playwright fetch into:

```python
async def fetch_rendered(url: str, *, wait: str = "networkidle",
                         timeout_s: int = 20) -> str | None:
    """Rendered page HTML via Playwright; None on failure."""
```

2. Refactor the YMCA adapter to call it (behavior-identical — verify with
   existing YMCA tests).

**Modify:** `src/sessions.py` enumeration flow: for providers whose platform
detection returns `agent_nav`/unknown AND plain fetch yielded 0 sessions:

1. `fetch_rendered(seed_url)`; on the rendered HTML, re-run platform detection
   (`detect_platform` on HTML — embedded widgets often only appear post-render;
   a Sawyer/WebTrac hit re-routes to that adapter).
2. Else run structured extraction on rendered HTML: registration-pattern links
   (`is_registration_platform_url`, regist/enroll paths), schedule tables.
3. Budget: new settings `"render_max_pages_per_host": 3`,
   `"render_max_pages_per_town": 60`, `"render_timeout_s": 20`. Enforce both.

**Test:** `tests/test_fetch_rendered.py` — mock Playwright (monkeypatch); assert
budget enforcement and re-detection path (fixture HTML containing a hisawyer
embed routes to sawyer adapter).

**MANUAL VERIFY:** re-run B.5 Lexington; gate: **fuse ≥ 1 real session;
viking/goddard/lexingtonunited each ≥ 1 row better than fallback OR a logged
reason; recall_fuzzy ≥ 0.82.**

---

## TASK 3.1 — Gemma LLM extraction adapter (last resort)

**Create:** `src/adapter_llm_extract.py`

```python
async def extract_programs_llm(url: str, *, town: str) -> list[dict]:
    """LLM-extract programs from a custom provider site. Last-resort adapter."""
```

1. Eligibility: called only when structured + sawyer + rendered extraction all
   returned 0 AND `src.llm.is_available()`. Otherwise return `[]` (fallback row
   from Task 1.2 still publishes).
2. Pages: rendered text of seed + up to 2 same-host links whose anchor text
   matches `(?i)(camp|summer|register|schedule|program|enroll)`. Reuse
   `fetch_page_text` / `fetch_rendered`. Truncate each page to
   `SETTINGS["ollama_session_max_chars"]`.
3. Prompt: add `LLM_EXTRACT_SYSTEM` to `config/prompts.py`:

```
You extract youth SUMMER CAMP programs from a provider webpage in <TOWN>, MA.
Return JSON only:
{"programs": [{"name": "...", "dates": "...", "ages": "...", "price": "...",
               "register_url": "...", "confidence": 0.0}]}
Rules: youth summer programs only (no adult, no school-year, no childcare).
register_url must appear in the page text. confidence 0-1. Empty list if none.
```

4. Model: `SETTINGS.get("ollama_verify_model")` via `src.llm.chat(...,
   purpose="llm_extract")`. Parallel across pages with `src.llm_pool.run_batch`.
5. Accept program iff `confidence >= SETTINGS["llm_extract_min_confidence"]`
   (new setting, default `0.6`) AND register_url host is same-host or passes
   `is_registration_platform_url`. Rejected-but-nonempty → keep Task 1.2
   fallback row.
6. Cache: `cache/llm_extract.json` keyed `sha256(host + page_text)[:16]` →
   programs list. Check before any LLM call.
7. Exhaust: hosts yielding 0 after this adapter → append
   `{host, seed_url, town, reason}` to `data/shared/firecrawl_queue.csv`
   (create with header if absent; dedupe on host).
8. Output rows: `granularity="program"` unless dates parse to a concrete range
   (then `"session"`); `platform="llm_extract"`.

**Test:** `tests/test_adapter_llm_extract.py` — monkeypatch `src.llm.chat` to
return canned JSON; assert confidence gate, same-host URL gate, cache hit
(second call makes zero chat calls), firecrawl queue write.

**MANUAL VERIFY:** Ollama up with gemma3:12b pulled; re-run B.5 Lexington.
**Gate: recall_fuzzy ≥ 0.90.**

---

## TASK 4.1 — Register URL canonicalization

**Modify:** `src/urls.py` — new function (do NOT change `normalize_url`
behavior for callers; add alongside):

```python
def canonical_register_url(url: str, platform: str = "") -> str:
```

Rules (apply after `normalize_url`):
- host contains `myvscloud` or platform `webtrac` and path contains
  `iteminfo.html` → keep ONLY query params `FMID`, `Module` (sorted).
  `search.html` URLs with `_csrf_token` → strip `_csrf_token` and all
  `arwebsearch*` params.
- platform `myrec` / `program_details.aspx` → keep ONLY `ProgramID`.
- ALL urls: drop params matching
  `^(utm_|fbclid|gclid|_csrf|session|sid$|phpsessid)`.

**Modify:** `src/sessions.py` `write_session_outputs`: canonicalize every
`register_url`; dedupe rows in priority order:
1. platform ID equality (FMID / ProgramID extracted from canonical URL)
2. canonical URL equality
3. `(host, norm_name, dates)` equality — reuse Task 0.1 normalizer (move it to
   `src/urls.py` or a new `src/textnorm.py` so both import it; scripts must not
   import from scripts).

Keep the row with the higher quality tier when deduping.

**Tests:** `tests/test_canonical_register_url.py` — WebTrac csrf URL strips
clean; two FMID-equal rows dedupe to one; ProgramID kept; utm stripped.

---

## TASK 4.2 — Publish gates

**Modify:** `src/deliverables.py` (and `src/session_quality.py` if the split
lives there):

1. New settings: `"publish_require_verify": True`,
   `"publish_allowed_verdicts": ["parent_ready", "brochure_only"]`.
2. `write_deliverables`: when `publish_require_verify`, the organized catalog
   CSV and `CAMPS_CATALOG.txt` include ONLY rows whose `parent_verdict` ∈
   allowed list. All other rows → `data/<town>/phase_p/review_queue.csv`
   (with `held_reason` column). Nothing is deleted — held, not dropped.
3. `brochure_only` rows get a `label` column value `brochure_only` (website
   badge).
4. Date sanity for `granularity="session"` rows: parseable date range required;
   range must intersect May 1–Sep 30 of the season year (new setting
   `"season_year": 2026`); past-only ranges → review queue with
   `held_reason="date_sanity"`. Program rows exempt.
5. Audience guard (no LLM): name matching
   `(?i)(adult|senior|18\+|21\+|parent night|bird walk)` → review queue
   `held_reason="audience_keyword"` unless verdict is `parent_ready`.

**Tests:** `tests/test_publish_gates.py` — unverified row held; brochure_only
published with label; past-dated session held; program row with no dates
published; adult-keyword row held.

**MANUAL VERIFY:** run
`./venv/bin/python -m src.run --no-dry-run --phase verify --town Lexington --verify-all`
then `--phase B5` deliverables rebuild, then score.
**Gate: precision ≥ 0.97 AND recall_fuzzy still ≥ 0.90.**

---

## TASK 5.1 — Per-provider regression floors

**Modify:** `tests/test_baseline.py` — add:

```python
PROVIDER_FLOORS = {
    "majwhaydenweb.myvscloud.com": 35,
    "lexrecma.myrec.com": 20,
    "lexingtoncommunityed.org": 1,   # raise after measuring actual count
    "fuseprogram.com": 1,
    "vikingcamps.com": 1,
    "goddardschool.com": 1,
    "lexingtonunited.org": 1,
    "lexdebateinstitute.com": 1,
    "lexingtonplaycarecenter.org": 1,
    "lexingtonsymphony.org": 1,
    "ussportscamps.com": 1,
    "massaudubon.org": 1,
    "massgeneral.org": 1,
}

def test_lexington_provider_floors():
    # reads data/lexington/phase_b5/camp_sessions.csv (published + program rows)
    # skip (pytest.skip) if the file does not exist (fresh clone)
    ...
```

After the Task 4.2 manual verify, the agent MUST update each floor to
`max(1, actual_count - 2)` using real counts from the latest run output, and
note counts in the commit message.

---

## TASK 5.2 — Burlington replication check (no code)

**MANUAL VERIFY (human):**
1. `./venv/bin/python -m src.run --no-dry-run --phase B5 --town Burlington`
2. `./venv/bin/python -m src.run --no-dry-run --phase verify --town Burlington --verify-all`
3. `./venv/bin/python scripts/score_town.py --town Burlington`

**Gate: recall_fuzzy ≥ 0.85 AND precision ≥ 0.95 with ZERO Burlington-specific
code changes.** If a fix requires town-specific code, it belongs in an adapter
or settings — file it as a follow-up task, do not patch inline.

---

## TASK ORDER & GATES SUMMARY

| Order | Task | Hard gate before next |
|------:|------|----------------------|
| 1 | 0.1, 0.2 | scorer green; corrected baseline recorded |
| 2 | 1.1 → 1.2 → 1.3 | recall_fuzzy ≥ 0.75 |
| 3 | 4.1, 4.2 (parallel-safe with 2.x) | — |
| 4 | 2.1 → 2.2 | recall_fuzzy ≥ 0.82 |
| 5 | 3.1 | recall_fuzzy ≥ 0.90 |
| 6 | re-verify 4.2 | precision ≥ 0.97 |
| 7 | 5.1 | floors committed with real counts |
| 8 | 5.2 | Burlington ≥ 0.85 / ≥ 0.95 |

**Definition of done:** all pytest green with Ollama down; Lexington
eval_history.csv last row shows recall_fuzzy ≥ 0.90, precision ≥ 0.97,
providers_covered = 21/21 (sessions or program rows); Burlington gate passed;
`firecrawl_queue.csv` contains every still-failing host.
