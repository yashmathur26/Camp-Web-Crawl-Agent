# Part C Roadmap — Parent-Perspective Gap Fill with Gemma

**Goal:** After Phases A→B→B.5→Q→P→trail complete for a town, run Part C to audit the catalog *as a parent would*, find every category hole (all sports, arts, music, instruments, STEM, nature, etc.), and fill it with niche/local providers — so that (1) the Firecrawl extraction phase has a deep pool of camps, and (2) **any category a parent searches on the website has at least one correlating result in every town** (or an explicit nearest-town substitute).

**Framing:** This is an *upgrade*, not a rebuild. The repo already has `--phase gap` (`src/agentic_gap.py`), the parent auditor (`src/parent_auditor.py`), a 24-category taxonomy (`config/gap_taxonomy.py`), and ~150 niche activities in `config/keywords.py` (`_SPORTS_ACTIVITIES`, `_ARTS_ACTIVITIES`, `_STEM_ACTIVITIES`, `_FUN_ACTIVITIES`). Part C = Gemma swap + taxonomy expansion + smarter categorization + regional sharing + coverage guarantee + multi-town orchestration.

**Budget posture:** Search credits are NOT the constraint. Worst case ~150 categories × 54 towns × 2 query variants ≈ 16,200 queries ≈ $10–16 (Serper) or ~$10 (DataForSEO standard). Spend freely on search; control cost on crawl/enumeration (which is wall-clock, not dollars).

---

## Stage 0 — Install Gemma & swap models (Day 1, ~1 hour)

### 0.1 Install (run on your Mac)

```bash
# Ollama already installed (you run llama3.2 today). Just pull Gemma 3:
ollama pull gemma3:1b      # 0.8 GB  — ultra-fast filter
ollama pull gemma3:4b      # 3.3 GB  — fast classifier / categorizer
ollama pull gemma3:12b     # 8.1 GB  — verifier + parent auditor (needs 24GB+ RAM)

# Verify
ollama run gemma3:4b 'Respond with JSON only: {"ok": true}'
```

**RAM sizing:**

| Mac RAM | fast model | verify/auditor model |
|---------|-----------|----------------------|
| 16 GB   | `gemma3:1b` | `gemma3:4b` |
| 24 GB   | `gemma3:4b` | `gemma3:12b` |
| 32 GB+  | `gemma3:4b` | `gemma3:12b` (can raise concurrency to 4) |

Gemma 3 follows Ollama's `format: "json"` constraint well, so `src/llm.py` needs no protocol changes.

### 0.2 `config/settings.py` diff (24 GB example)

```python
"ollama_model":        "gemma3:12b",   # was "llama3.2"  (agent + auditor)
"ollama_filter_model": "gemma3:4b",    # was "llama3.2"
"ollama_fast_model":   "gemma3:4b",    # was "llama3.2:1b"
"ollama_verify_model": "gemma3:12b",   # was "llama3.2"
"ollama_classify_concurrency": 3,      # keep; raise to 4 only on 32GB+
"ollama_verify_concurrency":   2,
"ollama_keep_alive":   "30m",
```

### 0.3 Patch `resolve_model()` fallback chain in `src/llm.py`

The current fallback list hardcodes llama names. Add gemma entries so a missing tag degrades gracefully:

```python
for fallback in (
    SETTINGS.get("ollama_fast_model"),
    "gemma3:4b",
    "gemma3:1b",
    SETTINGS.get("ollama_verify_model"),
    SETTINGS.get("ollama_filter_model"),
    SETTINGS["ollama_model"],
    "gemma3:12b",
    "llama3.2",          # legacy safety net
    "llama3.2:latest",
):
```

### 0.4 Smoke test

```bash
./venv/bin/python -m src.run --dry-run --town Lexington          # config sanity
./venv/bin/python -m src.run --no-dry-run --phase verify --town Lexington --verify-max-llm 10
```

Check `logs/` for "Warmed up model: gemma3:..." and confirm JSON parse rate (no `OllamaError: Could not parse JSON`). If gemma3:12b verify calls exceed ~15s each, drop `ollama_verify_concurrency` to 1.

**Acceptance:** Phase P verify runs end-to-end on Lexington with Gemma, ≥95% JSON parse success, no model-reload thrash in Activity Monitor.

---

## Stage 1 — Generate the full taxonomy from existing activity lists (Day 1–2)

**Problem:** `GAP_CATEGORIES` has 24 buckets; the guarantee needs ~150. The activities already live in `keywords.py` — don't maintain two lists.

**Build:** rewrite `config/gap_taxonomy.py` to generate categories programmatically:

```python
from config.keywords import (
    _SPORTS_ACTIVITIES, _ARTS_ACTIVITIES, _STEM_ACTIVITIES, _FUN_ACTIVITIES,
)

# Tier 1 — CORE (must exist in EVERY town's catalog, searched unconditionally)
CORE_CATEGORIES = (
    "general_day_camp", "sports_multi", "soccer", "basketball", "swim",
    "art", "music", "theater", "dance", "stem", "coding", "robotics",
    "nature", "cooking", "preschool", "special_needs", "teen_leadership",
)

# Tier 2 — LONG TAIL (searched when missing; can resolve to nearest-town)
LONG_TAIL = { slugify(a): a for a in
    _SPORTS_ACTIVITIES + _ARTS_ACTIVITIES + _STEM_ACTIVITIES + _FUN_ACTIVITIES }

# 2–3 query variants per category (see Stage 3) generated from templates:
QUERY_TEMPLATES = (
    "{town} MA youth {activity} summer camp",
    "{activity} summer camp kids near {town} Massachusetts",
    "{activity} summer clinic registration {town} MA 2026",
)
```

Also add a `parent_synonyms` map per category ("voice and singing" → singing, vocal, choir; "ninja warrior" → obstacle, parkour) — this feeds both the categorizer (Stage 2) and your website's search → category mapping later.

**Acceptance:** `python -c "from config.gap_taxonomy import LONG_TAIL; print(len(LONG_TAIL))"` ≥ 140; unit test that every category has ≥2 templates and ≥1 synonym.

---

## Stage 2 — Gemma session categorizer (Day 2–3) ← biggest accuracy win

**Problem:** `_category_from_session()` substring-matches names/URLs. Quirky camp names ("Wizards & Wands," "Lexplorations: Tinker Lab") categorize as `None` → false holes → wasted searches AND false coverage confidence.

**Build:** `src/categorizer.py`

1. **Rules first** (free): expand the keyword map using `parent_synonyms` — catches ~60–70%.
2. **Gemma batch pass** for the remainder: batches of 15 session names → `gemma3:4b`, prompt returns `{"sessions": [{"name": ..., "categories": ["pottery","art"], "confidence": 0.0-1.0}]}`. A session can hold multiple categories (a "Circus & Tumbling" camp covers circus_arts + gymnastics).
3. **Cache** verdicts in `cache/session_categories.json` keyed by normalized session name + host (re-runs are free).
4. Write `category` / `categories` columns back into `camp_sessions.csv` and verified outputs — Firecrawl handoff inherits these tags for free.

Wire `parent_auditor._category_from_session` → categorizer. Keep the substring path as the no-Ollama fallback.

**Acceptance:** On Lexington's existing ~200 sessions, ≤10% categorized `None` (vs current majority); spot-check 30 by hand.

---

## Stage 3 — Coverage matrix + auditor upgrades (Day 3–5)

### 3.1 Coverage matrix deliverable (operationalizes the guarantee)

New `src/coverage_matrix.py` → writes per-town and county-wide:

- `data/<town>/phase_gap/coverage_matrix.csv` — rows = categories, cols = `parent_ready_count`, `brochure_only_count`, `status` (covered / hole / exhausted / nearest_town:<town>), `example_provider`
- `data/shared/coverage_county.csv` — 54 towns × all categories, the master "can a parent find it?" grid. **This is your KPI artifact.**

### 3.2 Multi-variant hole searches

In `agentic_gap._search_holes`: each hole runs up to 3 query variants (Stage 1 templates), stopping early when a variant yields a new in-state, non-aggregator host. Variant 3 widens to "near {town}" / adjacent-town phrasing.

### 3.3 Exhausted-state memory

Extend `cache/gap_hole_searches.json` entries to `{searched_at, attempts, status}`. After 2 rounds × 3 variants with zero valid hosts → `status: "exhausted"`, TTL 60 days (`gap_hole_exhausted_days: 60` in settings), and the coverage matrix records the nearest covered town for that category (Stage 4 adjacency). Stops the engine from re-buying the same dead searches every week.

### 3.4 Parent-persona auditor prompt for Gemma

Replace `PARENT_AUDITOR_SYSTEM` with a richer persona: "You are a Lexington MA parent with kids aged 4–16 planning summer. Given covered categories and counts, list what you'd search for and NOT find. Consider: every major sport + niche sports, instruments individually (piano, guitar, drums, voice), visual arts media, performing arts, STEM subfields, ages (preschool vs teen), special needs, half-day vs full-day, overnight." Gemma3:12b handles this with the existing JSON schema (`{"holes": [...]}`) unchanged.

### 3.5 Chain-branch allow rule

In `validate_search_results` / sources denylist: allow branded local-branch pages (Code Ninjas, School of Rock, Goldfish Swim, British Swim School, iD Tech @ local campus) when the URL/title carries a location signal (`/locations/<town>`, town name in title, MA zip). These are primary sources for niche categories — often the ONLY provider.

**Acceptance:** Lexington gap run produces `coverage_matrix.csv`; ≥90% of Tier-1 CORE categories covered; holes log shows variant attempts; exhausted entries persist across runs.

---

## Stage 4 — Regional provider sharing (Day 5–7) ← biggest coverage-per-dollar win

**Problem:** A Woburn gymnastics gym serves 6+ surrounding towns, but today each town re-searches and re-discovers it.

**Build:**

1. `config/town_geo.py` — lat/lon for all 54 towns (static, one-time).
2. `src/provider_registry.py` — county-wide registry `data/shared/provider_registry.json`: host → {name, address/town (from B.5/P data), categories, parent_ready}.
3. **Before** searching a hole in town X, query the registry for a provider in that category within `gap_share_radius_miles` (default 10; 15 for rare categories like fencing/sailing/equestrian). Hit → credit it to town X's coverage matrix as `covered_via:<provider_town>`, skip the search.
4. **After** any gap search finds a new provider, register it and back-fill every in-radius town's matrix.

Expected effect: town #1 (Lexington) does the heavy lifting; by town #20, most long-tail holes resolve from the registry; by town #54, gap searches drop to genuinely local-only categories. Cuts both credits and wall-clock dramatically.

**Acceptance:** Run gap on Lexington then Arlington; Arlington's audit log shows registry hits (skipped searches) for categories Lexington already filled.

---

## Stage 5 — Multi-town orchestration & budgets (Day 7–9)

1. **CLI:** `--phase C --all-towns` (or `--towns Lexington,Arlington,...`) loops `_run_gap_fill` per town with checkpoint file `cache/part_c_progress.json` (resume after interrupt — you learned this lesson in the pilot).
2. **Budgets:** replace global `max_searches_per_run` truncation with `gap_search_budget_per_town: 400` (generous — you won't hit it after Stage 4 sharing kicks in; town #1 might). Log spend per town to `data/shared/part_c_cost_ledger.csv`.
3. **Provider speed:** when provider is `serper`/`dataforseo`, set effective search delay to 0.2s (the 8.0s `delay_seconds` is for free scrapers only — make it conditional in `discover.py`).
4. **Order towns** by population descending (Lowell, Cambridge, Newton first) — big towns seed the provider registry fastest, maximizing Stage 4 savings for the rest.
5. **Nightly schedule:** extend the existing cron/launchd entry with `--phase C --all-towns --resume`.

**Cost & time projection (after Stages 1–4):**

| Item | Estimate |
|------|----------|
| Town #1 gap searches (full long tail) | ~250–400 queries (~$0.40) |
| Towns #2–10 | ~100–200 each |
| Towns #11–54 | ~30–80 each (registry hits dominate) |
| **Total search spend, all 54 towns** | **~$5–12** |
| Wall-clock per town (search + new-host B.5 + verify, Gemma parallel) | 20–60 min |
| **Total Part C wall-clock** | **~2–4 overnight runs** |

---

## Stage 6 — Firecrawl handoff manifest (Day 9–10)

New `src/handoff.py` → `data/shared/firecrawl_manifest.csv` (+ JSON):

- One row per **unique provider URL** (deduped county-wide via registry), columns: `url`, `provider_name`, `host`, `towns_served` (semicolon list), `categories`, `parent_verdict`, `source_phase` (A/B/C), `priority` (parent_ready first).
- Filter: in-state, non-aggregator, non-exhausted, quality-tier ≥ needs_trail.
- This is the single input file for your Firecrawl extraction run — category tags mean extraction can prioritize and your site can map search terms → providers immediately.

**Acceptance:** Manifest row count >> Phase A/B-only catalog; every Tier-1 category has ≥1 manifest row per town (direct or `covered_via`); zero aggregator hosts.

---

## Final acceptance criteria (the guarantee)

1. `coverage_county.csv`: 100% of Tier-1 CORE categories show `covered` in all 54 towns (direct or covered_via ≤10 mi).
2. Long-tail categories: every cell is `covered`, `covered_via`, or `exhausted` (with nearest-town substitute recorded) — **no cell is silently empty**.
3. Re-running `--phase C --all-towns` a second time costs <$1 (caches + registry + exhausted states absorb everything).
4. Firecrawl manifest delivered with category + town tags, deduped.

## Suggested order of work

| Day | Work |
|-----|------|
| 1 | Stage 0 (Gemma) + Stage 1 (taxonomy) |
| 2–3 | Stage 2 (categorizer) — test on existing Lexington sessions before any new searches |
| 3–5 | Stage 3 (matrix, variants, exhausted, persona, chains) — re-run Lexington gap |
| 5–7 | Stage 4 (geo registry) — validate on Lexington + Arlington pair |
| 7–9 | Stage 5 (orchestrator) — kick off overnight all-towns run |
| 9–10 | Stage 6 (manifest) → Firecrawl |
