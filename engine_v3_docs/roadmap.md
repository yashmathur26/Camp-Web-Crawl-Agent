# roadmap.md — Engine v3 Rebuild (Phases)

Goal: replace the old crawl-centric pipeline (`src/`) with a vendor-integration engine
(`engine/`) that, for ANY input town and ANY registration platform, produces a list of
camps where every row links to **the info page — the content-rich page a parent sees
right before registration** — with providers/groups listed AND each individual camp
enumerated under them. This output feeds the next stage: a Firecrawl pass for taxonomy
and vector analysis.

Guiding principle (corrected from v2): **the unit of work is `(vendor, org_id)`, not a
URL. Deterministic extractors do the work; the LLM only perceives rendered text; the eval
is the boss.**

Companion docs: `rules.md` (hard constraints), `implementation_plan.md` (design),
`task.md` (granular work units). Phases are strictly sequential. Do not start a phase
until the previous phase's Exit is green and its eval numbers are recorded.

---

## Phase 0 — Ground truth + eval harness  *(blocks everything)*

**Why first:** the previous pipeline marked four major fixes "complete" while all four
stayed broken, because there was no number that had to move. This phase creates that
number.

- Hand-enumerate Lexington ground truth (~150–250 rows: provider, program, session dates,
  true info URL) by visiting each of the 21 known providers like a parent would.
- Lower-fidelity ground truth (program level) for one structurally different second town
  (must include a vendor Lexington lacks, e.g. ActiveCommunities or RecDesk).
- Build `engine/eval/score.py`: program recall, session recall, precision, info-url
  validity (live-fetch each published info_url; ≥400 chars containing program name).
- Score the OLD pipeline's latest Lexington output to fix the baseline.

**Exit:** `python -m engine.eval --town lexington` prints a metrics table for the old
pipeline output (expected: program recall ≈ 20–30%); ground-truth CSVs committed.

---

## Phase 1 — Skeleton: model, registry, gate

- `engine/` package created with CI import-boundary check (R2).
- `engine/model.py`: Provider / Program / Session dataclasses + serialization to the
  four-file output schema (providers / programs / sessions / gaps).
- `engine/registry/`: YAML schema + loader; hand-write `towns/lexington.yaml` from the
  old `scripts/fingerprint_providers.py` PROVIDERS dict with resolved `(vendor, org_id)`.
- `engine/validate/gate.py` (the ONE publish gate) + ported `enrollment_signals` regexes.
- `engine/run/runner.py` v0: registry → stub extractor → schema-valid output.

**Exit:** runner emits schema-valid (empty) output for Lexington; gate unit tests pass
(chrome-name → gap, empty-info-page → gap, real row → published).

---

## Phase 2 — Fetch layer

- `engine/fetch/`: one plain path, one rendered path (fixed-wait, 20s hard cap, single
  attempt, never networkidle), normalized-URL cache (memory + disk), media-class refusal,
  per-provider wall-clock budget, full fetch logging (ms + chars).

**Exit:** offline tests against saved fixtures + one live smoke run prove: cap enforced,
cache hit on repeat URL, a hanging URL costs ≤ cap once, media URLs refused.

---

## Phase 3 — Vendor extractors wave 1: WebTrac, MyRec, ACTIVE

The proof-of-architecture wave — one extractor per failure archetype:

- **WebTrac (port):** lift the working adapter; group sessions into Programs
  (10 "Lower Camp" weeks = 1 program, 10 sessions); info_url = iteminfo page.
- **MyRec (rewrite):** extract everything from the server-rendered catalog listing rows;
  NEVER fetch `program_details.aspx` shells (171-char JS shells; cost ~25 min/town before).
  `info_confirmed` verdict publishes — real camps stop dying for lacking a cart CTA.
- **ACTIVE (new):** resolve org + season, hit the JSON catalog endpoint behind
  `campscui.active.com`, map sessions; capture API fixture. Recovers Munroe and every
  ACTIVE org in every future town.

**Exit:** Lexington program recall ≥ 70%; precision 100% (gate-enforced); LexRec ~26 camps
and Munroe's full roster published with valid info_urls; old baseline beaten.

---

## Phase 4 — Vendor extractors wave 2

Sawyer (embedded JSON), CampBrain (queue-it handling or honest `gap: blocked`), enrollsy,
Daxko, CommunityEd/WooCommerce (render-path pagination of `find-a-class`; `/class/{slug}`
pages ARE the info pages — must recover the full ~60–70 Lexplorations set), plus
RecDesk/CivicRec/CommunityPass/Ultracamp as the gaps report demands (R8.1).

**Exit:** Lexington program recall ≥ 90%; Lexplorations full set recovered; every wave-2
vendor has a fixture-backed offline test.

---

## Phase 5 — Generic long-tail path

For `vendor: unknown` providers — the "any platform, no matter how bad" clause:

- Rendered fetch → deterministic harvest (headings, link clusters, JSON-LD) → bounded
  same-host follow (depth ≤ 2, scored, budgeted) → LLM extraction under R3 → gate.
- Thin/blocked/empty sites produce diagnosed gaps, never silent zeros or junk rows.

**Exit:** every Lexington long-tail provider (lexfarm, lca.edu, Hancock, playcare, FUSE,
debate institute, Waldorf…) either publishes real programs or appears in gaps with the
correct diagnosis; zero published rows from <400-char pages; precision holds at 100%.

---

## Phase 6 — Discovery → registry proposer

Port Phase A (search + denylists + geo + fingerprinting) but its output becomes registry
**proposals** (`towns/<town>.proposals.yaml` with evidence) for a ~10–30 min human review —
never a direct crawl set. This is the "any town I give" entry point:
`engine propose --town X` → review → `engine run --town X`.

**Exit:** proposer run on a never-touched town surfaces ≥ 80% of its ground-truth
providers; approval flow documented.

---

## Phase 7 — Runner hardening + observability

Parallel per-provider jobs, resumability (finished providers skipped on rerun),
wall-clock budgets enforced, plain-English per-provider narration, run summary =
eval table + gaps table + timings.

**Exit:** full Lexington run < 15 min cold / < 3 min warm; kill -9 mid-run and rerun
completes without re-fetching finished providers.

---

## Phase 8 — Multi-town validation, cutover, deletion

- Run on 3 towns: Lexington, the Phase-0 second town, and one cold town through the full
  propose → approve → run flow.
- Hand the output to the Firecrawl stage and confirm it receives content-rich pages
  (the true end-to-end test of the product contract).
- Delete superseded `src/` modules and the broken characterization tests; update README.

**Exit:** program recall ≥ 90% on ground-truth towns; info-url validity 100% on published
rows; cold town yields a credible catalog + diagnosed gaps with < 30 min registry review;
Firecrawl stage consuming engine output; old pipeline deleted.

---

## Sequencing rules

- Phase 0 blocks all coding. Phases 3→4→5 are the recall ladder; do not skip ahead to
  discovery (6) or performance (7) while recall is below target — that is exactly the
  trap the previous rebuild fell into.
- Record eval numbers at every phase exit in `engine/eval/history/`.
- Any phase may add vendors to the Phase-4 queue via `gaps.csv`, but only R8.1 admits
  them to active work.
