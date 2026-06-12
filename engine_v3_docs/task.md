# TASK.md — Engine v3 Work Units

Work strictly top-to-bottom. Do not start a task until the one above it is green. Every
task has a Definition of Done (DoD); a DoD that includes "eval" means run
`python -m engine.eval --town lexington` and paste the numbers into the commit message
(RULES R1). Design details: `implementation_plan.md`. Constraints: `rules.md`.

Tasks marked **[HUMAN]** require the operator, not the agent.

---

## Phase 0 — Ground truth + eval

- [ ] **0.1 [HUMAN]** Hand-enumerate Lexington ground truth →
  `engine/eval/ground_truth/lexington.csv`
  (columns: `provider_host, program_name, session_dates, true_info_url`).
  Visit all 21 providers from `scripts/fingerprint_providers.py`. Expect 150–250 rows.
  DoD: file committed; row count noted.
- [ ] **0.2 [HUMAN]** Program-level ground truth for one second town containing a vendor
  Lexington lacks (ActiveCommunities or RecDesk town preferred) →
  `engine/eval/ground_truth/<town>.csv`. DoD: file committed.
- [ ] **0.3** Create `engine/` package + `tools/check_imports.py` (fails on any
  `import src` / `from src` inside `engine/`) + wire into CI/pre-commit.
  DoD: a deliberate `import src` in a scratch engine file fails the check; removed after.
- [ ] **0.4** Implement `engine/eval/score.py` per plan §11 (program recall, session
  recall, precision, info-url validity with live fetch; `--offline` mode skips live
  fetch). CLI: `python -m engine.eval --town X [--input <sessions.csv>] [--compare a b]`.
  Writes `engine/eval/history/<ts>.json`.
  DoD: unit tests for the fuzzy matcher (exact, dated-variant, near-miss) pass.
- [ ] **0.5** Score the OLD pipeline's latest Lexington output
  (`data/lexington/phase_b5/camp_sessions.csv`) to fix the baseline.
  DoD: baseline numbers recorded in `engine/eval/history/baseline_old_pipeline.json`
  and pasted into the commit message.

## Phase 1 — Skeleton

- [ ] **1.1** `engine/model.py`: `Provider`, `Program`, `Session`, `Gap`, `FetchRecord`
  dataclasses with IDs, provenance (`extractor`, `fetched_at`, `content_chars`,
  `evidence_json`), and CSV (de)serialization matching plan §2 schema.
  DoD: round-trip serialization test passes.
- [ ] **1.2** `engine/registry/schema.py`: YAML loader + validator (required fields,
  known-vendor enum + `unknown`, alias handling). DoD: loader rejects a malformed file
  with a clear error; accepts a valid one.
- [ ] **1.3 [HUMAN-assisted]** Write `engine/registry/towns/lexington.yaml` from the
  PROVIDERS dict, resolving `(vendor, org_id)` where known; mark the rest
  `vendor: unknown`; encode the lexingtonma.gov → lexrecma alias.
  DoD: loader validates it; every ground-truth provider host appears.
- [ ] **1.4** Port `enrollment_signals` regex core → `engine/validate/signals.py` with
  its old tests adapted. DoD: tests green offline.
- [ ] **1.5** `engine/validate/gate.py` per plan §8 (name integrity, info-url invariant,
  evidence rules applied to extracted fields, optional register upgrade, geo).
  DoD: table-driven tests cover: chrome name → gap; empty info page → gap; PDF
  register → attachment not program; adult program → gap; real WebTrac row → published
  `parent_ready`; real MyRec-style row with listing evidence → published `info_confirmed`.
- [ ] **1.6** `engine/run/runner.py` v0 + `engine/run/report.py`: registry → stub
  extractor (returns `gap: needs_adapter` for all) → gate → four CSVs + narration log.
  DoD: `python -m engine.run --town lexington` emits schema-valid output where every
  provider is a diagnosed gap; counts in log == rows in CSVs.

## Phase 2 — Fetch layer

- [ ] **2.1** `engine/fetch/cache.py`: normalize_url-keyed (port `normalize_url` + tests),
  memory + sqlite at `data/cache/fetch_cache.db`, per-run namespace, TTL from config.
  DoD: repeat fetch of same URL in tests hits cache.
- [ ] **2.2** `engine/fetch/client.py`: `fetch_text` per plan §9 (httpx, robots,
  politeness, timeout, retry ×1 on connection error ONLY, media-class refusal,
  per-provider wall-clock budget object, full logging).
  DoD: stub-server tests prove timeout-no-retry, media refusal, budget exhaustion.
- [ ] **2.3** `engine/fetch/render.py`: `fetch_rendered` per plan §9 (Playwright,
  DOM-settle poll, 20s hard cap, SINGLE attempt, browser pool ≤2).
  DoD: test with a stub page that never settles costs ≤ cap exactly once;
  a normal JS page returns its rendered text.
- [ ] **2.4** Live smoke (manual): rendered-fetch one MyRec detail page and the Munroe
  ACTIVE org page; record chars + ms in the commit message. This is the empirical input
  to tasks 3.4 and 3.6.
  DoD: results recorded; no fetch exceeded cap.

## Phase 3 — Vendor wave 1

- [ ] **3.1** `engine/extract/base.py`: `Extractor` ABC + `ExtractResult` per plan §5;
  runner dispatch by vendor with `unknown → generic` (generic stubbed until Phase 5
  as `gap: needs_adapter`). DoD: dispatch unit test.
- [ ] **3.2** Port WebTrac → `engine/extract/vendors/webtrac.py` against existing
  fixtures; add Program grouping (normalized-name collapse per plan §2).
  DoD: fixture test yields the known 40 sessions grouped into the expected programs
  (e.g. Lower Camp = 1 program / 10 sessions); camp-scoped flag set (R4.2).
- [ ] **3.3** Run engine with WebTrac only; eval.
  DoD: Hayden fully published `parent_ready`; numbers in commit.
- [ ] **3.4** `engine/extract/vendors/myrec.py` REWRITE per plan §6: listing-row
  extraction only; never bulk-fetch detail shells; info_url decision encoded from the
  2.4 spike; capture a listing fixture.
  DoD: fixture test yields ≥ the 26 known LexRec camps with names + ProgramIDs + any
  listing dates; zero `program_details` fetches in the fetch log.
- [ ] **3.5** Eval after MyRec. DoD: LexRec camps published (`info_confirmed` acceptable);
  recall recorded.
- [ ] **3.6** `engine/extract/vendors/active.py` per plan §6: resolve org+season, call
  the JSON catalog endpoint, map sessions, choose info_url; save
  `tests/fixtures/active/munroe.json`.
  DoD: offline fixture test passes; live run publishes Munroe's roster.
- [ ] **3.7** Phase-3 exit eval. DoD: program recall ≥ 70%, precision 100%, old baseline
  beaten; numbers recorded in history + commit.

## Phase 4 — Vendor wave 2

- [ ] **4.1** `sawyer.py`: parse embedded JSON from activity-set fixtures (exist);
  activity-set page = info_url. DoD: robohub fixture test yields real names + dates.
- [ ] **4.2** `communityed.py` REWRITE per plan §6: render-path pagination of
  `find-a-class` + week categories; `/class/{slug}` = info_url; harvest week-label dates;
  prefix-scoped; capped. Delete the old `community_ed_session_count == 0` test.
  DoD: live Lexington run recovers the ground-truth Lexplorations set (~60–70);
  zero `/shop/` fetches.
- [ ] **4.3** `campbrain.py`: realistic-UA rendered attempt; queue-it still blocking →
  `gap: blocked` with evidence; merge with generic-path output from the provider's
  marketing site. DoD: Summers Edge produces either programs or a diagnosed gap — never
  an empty-name row.
- [ ] **4.4** `enrollsy.py`: probe for JSON endpoint, else rendered, else
  `gap: render_failed`. DoD: Waldorf produces programs or diagnosed gap.
- [ ] **4.5** `daxko.py`: port `_extract_daxko_sessions` + its swim-test exclusion test.
  DoD: ported test green.
- [ ] **4.6** Detection stubs for recdesk/civicrec/communitypass/ultracamp emitting
  `gap: needs_adapter`. DoD: unknown-vendor providers on those hosts gap correctly.
- [ ] **4.7** Phase-4 exit eval. DoD: program recall ≥ 90%; every wave-2 vendor has an
  offline fixture test; numbers recorded.

## Phase 5 — Generic long-tail

- [ ] **5.1** `engine/extract/llm.py` per plan §10: single `extract_programs` entry,
  hard ≥400-char input guard, JSON-repair + one retry, None on failure (caller fails
  open), full call logging.
  DoD: guard test (399 chars raises); repair test; failure-returns-None test.
- [ ] **5.2** `engine/extract/generic.py` per plan §7: rendered seed → deterministic
  harvest (JSON-LD, heading/link clusters; port `crawl_link_score`) → bounded follow
  (depth ≤2, scored, budgeted, media refusal) → LLM extraction → candidates to gate.
  Empty/blocked/thin → diagnosed gap.
  DoD: fixture tests: a marketing site with 5 camps yields 5 candidates; a 0-char site
  yields `gap: empty` with ZERO LLM calls (assert call count).
- [ ] **5.3** Run full Lexington; triage every long-tail provider (lexfarm, lca.edu,
  Hancock, playcare, FUSE, debate institute, Waldorf, symphony, MGH, Audubon, US Sports).
  DoD: each publishes real programs OR appears in gaps with the correct diagnosis;
  off-topic providers (MGH, Audubon) emit zero junk rows; precision still 100%.
- [ ] **5.4** Phase-5 exit eval recorded.

## Phase 6 — Registry proposer

- [ ] **6.1** Port Phase A search + denylists + geo into `engine/registry/proposer.py`;
  port fingerprint platform-resolution; output `towns/<town>.proposals.yaml` with
  evidence per candidate. DoD: proposer never writes into `towns/<town>.yaml` directly.
- [ ] **6.2** `engine propose --town <X>` CLI + a short REGISTRY_REVIEW.md describing the
  human approval flow. DoD: docs committed.
- [ ] **6.3 [HUMAN]** Run proposer on a fresh town; review/approve; measure proposal
  coverage vs that town's ground truth (≥80%). DoD: coverage number recorded.

## Phase 7 — Runner hardening

- [ ] **7.1** Parallel per-provider asyncio jobs (config `concurrency`), host-aware
  politeness preserved through the shared fetch layer. DoD: Lexington wall-clock < 15 min
  cold.
- [ ] **7.2** Resumability: `data/<town>/engine/checkpoint.json`; rerun skips finished
  providers. DoD: kill -9 mid-run, rerun completes without re-fetching finished
  providers (assert via fetch log).
- [ ] **7.3** Report polish: per-provider narration blocks; run summary = eval table +
  gaps table + timings. DoD: warm-cache rerun < 3 min; summary readable by a human in
  one screen per provider.

## Phase 8 — Multi-town validation + cutover

- [ ] **8.1** Full runs on Lexington + second GT town + one cold town (via 6.3 flow);
  evals recorded. DoD: recall ≥90% on GT towns; info-url validity 100% on published rows.
- [ ] **8.2 [HUMAN]** Hand `programs.csv`/`sessions.csv` to the Firecrawl stage; confirm
  extraction quality on a sample of 20 info_urls. DoD: sign-off noted.
- [ ] **8.3** Delete superseded `src/` modules (per implementation_plan §14 DELETE rows)
  and the broken characterization tests; keep ported/REUSE assets; update README to the
  three-stage engine. DoD: test suite green; `python -m engine.run --town X` is the only
  documented entry point.
- [ ] **8.4** Final eval history entry tagged `cutover`; old-pipeline baseline retained
  for the record.
