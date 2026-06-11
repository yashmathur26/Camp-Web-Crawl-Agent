# roadmap2.md — B.5 Accuracy & Output-Quality Refactor

This is the **second** refactor of Phase B.5. The first refactor (`roadmap.md`,
`TASK.md`, `RULES.md`, `IMPLEMENTATION_PLAN.md`) replaced the one-hop picker with the
bounded recursive **navigator_v2**. That work shipped and the navigator now crawls,
fans out, and verifies. This refactor fixes the thing the navigator does **badly**:
the *quality* of what it emits.

Pair this file with `task2.md` (work units), `rules2.md` (guardrails), and
`implementation_plan2.md` (technical design). Where these conflict with the v1 docs,
**v2 wins** for the areas it covers (naming, filtering, rendering, validation); the v1
docs still govern the navigator's traversal skeleton.

---

## 1. Why this refactor exists — the evidence

A full Lexington run (21 providers, 59 minutes) produced `baseline=78 new=77
parent_ready=24 regressions=4`. The "77 camps" headline is misleading. Concrete
garbage that was **saved as youth summer camps**:

| Provider | What got saved | What it actually is |
|---|---|---|
| lexingtonsymphony.org | 3 rows named **"Back to Top"** | a scroll-to-top button label |
| massgeneral.org | 2 rows named **"skip to Cookie Notice"**, one linking to `ncbi.nlm.nih.gov/pubmed/26933943` | a cookie-banner skip-link + a research paper |
| ussportscamps.com | **"Lexington"**, **"Camp program"**, register = site homepage | nav crumbs, no real session |
| lexingtonma.gov | **"Lexrec Summer Day Camp Daily Schedule"**, no register URL | a printable PDF timetable |
| hancocknurseryschool.org | 2 camps with invented ages/dates | **fabricated** from a 92-char login page |

And the inverse — real camps **thrown away**:

| Provider | Found | Kept | Why |
|---|---|---|---|
| therobohub.com (Sawyer) | 171 | **0** | every name became "See Details"/"Register"/"Join Waitlist" |
| summersedgedaycamp.com (CampBrain) | 1 | 0 | name = "Register Here" |
| munroecenter.org (active.com) | 2 | 0 | names = "Themunroecenterforthearts", a `.png` filename |
| lexingtonplaycarecenter.org | 1 | 0 | name = "Skip to content" |

The pattern is consistent: the system is **accurate on clean, server-rendered sites**
(WebTrac/Hayden = 40 good rows; MyRec catalog = 24 real names) and **falls apart on
JavaScript/portal sites**, where it (a) records button/menu chrome as the camp name,
(b) can't confirm registrability, (c) sometimes invents data, and (d) wanders off-topic.
Then a name-only filter both keeps junk that happens to contain "camp/summer" and
discards real camps whose names got mangled — with no working AI rescue and no final
sanity check.

---

## 2. Root-cause map (what each phase attacks)

1. **Name provenance is broken.** Names are taken from on-page link text
   (`_clean_name(l.get("text"), u)`), which on JS/portal pages is chrome
   ("Back to Top", "See Details", "Skip to content", "Manage Cookies").
   → **Phase 1**
2. **JS pages are read before they render.** `fetch_wait_until` only uses
   `networkidle` for `register`/`portal` kinds or hosts in
   `parent_verify_networkidle_hosts`; everything else is `domcontentloaded`. MyRec
   detail pages return 171 chars; active.com/enrollsy return 0. Real names + cart
   signals are in the late-loaded DOM or an embedded JSON payload.
   → **Phase 2**
3. **Filtering judges the label, not the thing.** `classify_session` keeps/drops on a
   name-dominated text blob; the LLM tie-breaker (`_apply_focus_llm_tiebreaker`) is
   gated off (`ollama_focus_verify` false) and is fail-closed.
   → **Phase 3**
4. **The system fabricates and wanders.** Extraction runs on `llama3.2:1b` against
   login/empty pages (Hancock); fan-out drifts into unrelated sections (Mass General
   psychiatry/imaging, Mass Audubon explosion) and accepts off-domain register URLs
   (ncbi.nlm.nih.gov).
   → **Phase 4**
5. **Nothing validates the final row.** A session with a chrome name, no register URL,
   no age/date/price, or an off-topic link still gets written to the CSV.
   → **Phase 5**
6. **Wasted work / duplicate funnels / verdict policy.** lexingtonma.gov re-derives the
   MyRec catalog that provider 2 already covers; no cross-provider fetch cache; MyRec
   can never reach `parent_ready` and that's never decided on purpose.
   → **Phase 6**

---

## 3. Phase sequence

Each phase is independently shippable and gated behind a flag where it changes behavior
(`rules2.md` §Flags). Do not start a phase until the one before it is green against the
Phase 0 baseline.

### Phase 0 — Safety net & failure corpus *(do first, no behavior change)*
Capture the current bad run as a frozen baseline and turn every failure above into a
fixture + a **characterization test that asserts the current WRONG output**. This lets
later phases prove improvement instead of trading one bug for another.
**Exit:** `pytest` green; `data/_baseline_v2/` committed; a `data/junk_audit.csv`
listing every bad row in the current run with a machine-checkable reason.

### Phase 1 — Name integrity *(highest leverage)*
Stop ever saving chrome/button/menu text as a name. Introduce a `CHROME_LABELS`
denylist and a `name_source` provenance field. A row whose only available name is chrome
is marked `needs_name`, never published with that string.
**Exit:** zero rows in a fresh run named from `CHROME_LABELS`; Hayden/MyRec real names
unchanged; robohub rows now carry either real names or `needs_name` (not "See Details").

### Phase 2 — Render correctness
Make JS/portal pages actually render before reading: extend the wait policy, add a
post-idle settle + one retry, and add **structured extraction from embedded JSON** for
Sawyer (`activity-set` payload) and MyRec. This is what converts robohub's 171 and the
MyRec funnel from chrome into real titles + dates.
**Exit:** robohub yields real camp names with dates; MyRec detail pages yield non-empty
content; active.com/enrollsy no longer return 0 chars on the retry path (or are cleanly
marked `needs_js`).
*Adopt here:* the **capture-then-extract** split (see §6). Once a page renders, persist
the rendered HTML/text to disk before parsing, so extraction never races page load again.

### Phase 3 — Evidence-based filtering
Filter on age/date/price/registrability, not just the name. Keep items from camp-only
catalogs by default (as WebTrac already does). Turn on `ollama_focus_verify`, make the
tie-breaker **fail-open** for camp-context ambiguous names when the model is unavailable,
and route it to the instruct model not 1B (see §6 for the model choice — Gemma 4 12B).
**Exit:** "Super Soccer Stars", "Quickball", "radKids", "Challenger Tiny Tykes Soccer",
"Kidcreate", "Mystic Valley Music Together" are kept; PDF-timetable and membership rows
still dropped.

### Phase 4 — Anti-fabrication & anti-drift
Never run LLM extraction on login-wall/empty/thin pages — mark `needs_js`/`login_wall`
instead. Scope fan-out and register URLs to the provider host + an allow-list of known
registration hosts; add an on-topic gate so the crawl stops drifting (Mass General,
Mass Audubon).
**Exit:** no fabricated rows from thin/login pages; no `ncbi.nlm.nih.gov` or homepage
register URLs; Mass General/Mass Audubon finish without emitting off-topic rows and
without burning the full fetch budget on unrelated pages.

### Phase 5 — Output validation gate *(the backstop)*
Before any session is written, it must pass `validate_session()`: real name (not chrome,
not a bare ID, not a filename), a registrable URL on an allowed host, **at least one** of
{age, date, price}, and an on-topic check. Failures go to a quarantine file, not the
deliverable CSV.
**Exit:** every row in `camp_sessions.csv` passes the gate; everything else is in
`camp_sessions_quarantine.csv` with a reason; the run summary reports
`published / quarantined / fabricated_blocked`.

### Phase 6 — Dedupe, budget, verdict policy
Detect funnel duplicates (lexingtonma.gov → lexrecma.myrec.com) and merge; add a
run-level fetch cache keyed on `normalize_url`; decide MyRec's verdict explicitly
(`brochure_only` shipped honestly, or a render/Firecrawl confirm pass to reach
`parent_ready`).
**Exit:** no provider re-fetches another provider's pages; documented MyRec verdict
policy; runtime down meaningfully from the 59-minute baseline.

### Phase 7 — Cut over & measure
Re-run Lexington + Burlington, diff against `data/_baseline_v2/`, and enforce the quality
gate in CI.
**Exit:** `junk_rate ≈ 0`, `parent_ready` up vs baseline, `fabricated = 0`, no real-camp
regressions; flags flipped on by default; v2 docs match reality.

---

## 4. Target metrics (Lexington, vs the 77/24 baseline)

| Metric | Baseline | Target |
|---|---|---|
| Junk rows published (chrome name / no register / off-topic) | ~10+ | **0** |
| Fabricated rows (from login/empty pages) | ≥2 | **0** |
| Sawyer (robohub) real camps published | 0 | **most of 171** |
| `parent_ready` count | 24 | **↑** (Sawyer + WebTrac + community_ed) |
| Real youth programs wrongly dropped (Super Soccer Stars etc.) | ~6+ | **0** |
| Runtime | 59 min | **↓** (dedupe + cache + drift guard) |

"Junk row" is defined precisely in `implementation_plan2.md` §7 so it can be measured by
script, not opinion.

---

## 5. Ordering rationale

Phase 1 first because clean names are a precondition for *every* downstream step:
filtering, dedupe, and the validation gate all key off the name. Phase 2 second because
once names can be trusted, rendering is what unlocks the large hidden catalogs (Sawyer,
MyRec). Phases 3–5 progressively tighten correctness (recover real, reject fake, then a
final backstop). Phase 6 is efficiency and policy. Phase 7 locks it in. Do not reorder;
the validation gate (5) will mostly pass only because 1–4 made the data clean — building
5 first would just quarantine everything.

---

## 6. Local model upgrade & capture-then-extract

Two ideas worth adopting from the "local Gemma + filesystem + RAG" suggestion. We take
the model upgrade and the capture/extract split; we **defer RAG** (see §6.3 for why).

### 6.1 Replace the 1B extraction model with Gemma 4 (12B)

A big share of the bad output came from running extraction and the focus tie-breaker on
`llama3.2:1b` — that is the model that invented Hancock's camp dates from a 92-char login
page. A 1B model is fine as a fast yes/no classifier and nothing more. Swap the
extraction/tie-breaker model to a strong, current local instruct model — **Gemma 4 12B**
(Google's open-source, Apache-2.0 model; multimodal, long-context, runs locally on ~16GB
VRAM/unified memory, available via Ollama/llama.cpp/MLX). Tie this to the Phase 3 work:

- `ollama_verify_model` → Gemma 4 12B (instruct). Used for `verify_youth_summer`
  (tie-breaker) and `camp_session_extract` (prose extraction).
- `ollama_fast_model` → keep a small/fast model (1B–3B) for the binary
  is-this-a-camp-page classifier only.
- Add the model string to `resolve_model`'s fallback chain so a missing pull degrades
  gracefully instead of erroring.
- **Quant/RAM note:** 4-bit ≈ 8–14GB, 8-bit ≈ higher; pick the largest quant that fits
  the run machine. If 12B is too heavy for the host, an E4B/edge Gemma 4 still beats 1B
  for extraction. Confirm sizes/quants against current docs before pinning a tag.

This is the single cheapest accuracy win outside Phases 1–2: better judgment on the
ambiguous keep/drop calls and far less fabrication, for a model swap plus slower
per-call latency (acceptable — accuracy is the priority).

### 6.2 Capture-then-extract (separate collecting from understanding)

Today the navigator parses each page live and decides on the spot what's a camp — under
page-load timing pressure, which is why it read chrome and empty shells. Adopt the
suggestion's good half: once Phase 2 renders a page, **persist the rendered text/HTML to
disk** (a per-town `data/<town>/phase_b5/captured/` cache — plain files, "Obsidian-style"
only in the sense that it's flat markdown/text on disk) and run extraction against the
saved copy. Benefits:

- Extraction never races page load again (the captured copy is already fully rendered).
- The same capture can be re-extracted offline with a better model without re-crawling
  (cheap iteration while tuning Gemma 4 prompts).
- Doubles as the Phase 0 fixture corpus and the Phase 6 fetch cache — one mechanism.

**Caveat that keeps this honest:** capturing raw HTML only helps if the capture step
*rendered first*. Saving an un-rendered shell to disk just stores the same empty page a
smarter model still can't read. So this rides on Phase 2 — it is not a substitute for the
render/settle/retry work.

### 6.3 RAG — deferred, and why

RAG (index the captured corpus, answer questions against it) solves "let me ask questions
over a pile of documents." Our deliverable is a clean list of camps with register links,
not a Q&A system — the failures were rendering, naming, and validation, not retrieval.
Adding a vector index + retrieval layer is machinery that doesn't touch any root cause in
§2. **Defer** unless a real downstream need appears (e.g. a parent-facing "find me camps
for ages 6–8 in July" query surface), at which point RAG over the §6.2 captured corpus is
the natural place to add it — after the data is trustworthy, not before.

---

## 7. Implementation status (as built)

Phases 0–6 are implemented behind flags and unit-tested; Phase 7 is the live
cut-over gate (`scripts/p7_measure.py`).

| Phase | What shipped | Key code | Flag (default) |
|---|---|---|---|
| 0 | Frozen bad run + machine-checkable junk audit | `src/junk_audit.py`, `data/_baseline_v2/`, `data/junk_audit.csv` | — |
| 1 | Name integrity (chrome never published; `name_source`) | `make_session` | `b5_name_integrity` (on) |
| 2 | Render: networkidle for JS hosts, thin-render settle/retry, JSON-LD, capture | `src/crawl.py`, `src/structured_extract.py`, `src/capture.py` | `b5_render_*`, `b5_capture_pages` (off) |
| 3 | Evidence-based filter + fail-open instruct tie-breaker | `src/relevance.py`, `verify_youth_summer` | `ollama_focus_verify` (on), `b5_focus_verify_fail_open` (on) |
| 4 | Anti-fabrication (`should_llm_extract`) + anti-drift (host-scoped register, off-topic fan-out) | `src/camp_validator.py`, `src/navigator.py` | — |
| 5 | Validation gate + quarantine CSV + run summary | `validate_session`, `write_session_outputs` | `b5_validation_gate` (on) |
| 6 | Fetch cache, cross-provider funnel dedupe, MyRec verdict policy | `src/fetch_cache.py`, `src/verdict_policy.py` | `b5_fetch_cache`, `b5_cross_provider_dedupe` (on), `b5_myrec_verdict` |
| 7 | Cut-over measurement vs `data/_baseline_v2/` | `scripts/p7_measure.py` | gate: `b5_navigator_v2` |

**Model routing:** navigation/extraction/tie-breaker run on `ollama_verify_model`
(the instruct model); `ollama_fast_model` (1B) is reserved for the binary
classifier. `resolve_model` no longer downgrades a bare base name to a smaller
variant. Pulling Gemma-4-12B (§6.1) is an ops step: set `ollama_verify_model` to
the pulled tag — `resolve_model` degrades gracefully if absent.

**Cut-over (Phase 7):** `b5_navigator_v2` flips to default-on only after
`scripts/p7_measure.py` confirms `junk_rate ≈ 0`, `fabricated = 0`, and
`parent_ready` not down vs `data/_baseline_v2/`.
