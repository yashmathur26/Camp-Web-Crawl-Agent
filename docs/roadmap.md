# Roadmap — B.5 Navigator Refactor

Goal: turn B.5 from a one-hop link picker into a bounded recursive navigator that
models the parent flow (landing → info → register), verifies registrability inline,
and fans out across multi-camp sites — **while reusing the existing discovery layer,
structured adapters, and enrollment signals.**

Guiding principle: *deterministic code controls traversal; the LLM only does perception.*

---

## Phase 0 — Safety net (before touching anything) ✓

**Why:** the adapters and signals are the valuable, fragile parts. Lock their behavior
before refactoring around them.

- [x] Snapshot B.5 output → `data/_baseline/{lexington,burlington}/baseline.json`.
- [x] Real HTML fixtures (crawl path) under `tests/fixtures/` for four platforms.
- [x] `tests/test_characterization_*.py` lock adapters, detect, enumerate, signals.

**Exit:** `pytest` green; baseline CSVs committed; you can diff any future run against them.

---

## Phase 1 — Three-node schema ✓

**Why:** every later step depends on being able to represent info_url separately from
register_url. Cheapest unblock.

- [x] Add `info_url` (and optionally `details_text`) to `make_session` and `SESSION_CSV_COLUMNS`.
- [x] Backfill existing adapters to set `info_url` where they already know it; default to "".
- [x] Update deliverables/quality writers to read the new column (no behavior change yet).

**Exit:** schema carries three URLs; existing run produces identical camps plus an empty
`info_url`; nothing downstream breaks.

---

## Phase 2 — Verification gate moves inline ✓

**Why:** "can a parent register" should be decided where the page is fetched, not a phase later.

- [x] Extract the deterministic check from Phase P (`enrollment_signals.py`) into a callable
  `verify_registrable(url, html) -> EnrollmentSignals` usable mid-traversal.
- [x] Make fetches that target register/portal pages use `networkidle` (JS-rendered portals).
- [x] Phase P stays as a batch re-verify / audit, but the navigator now sets `parent_verdict`
  itself when it has the page in hand.

**Exit:** a camp is only marked `parent_ready` after its register page was fetched and
signals confirmed a cart/price/CTA.

---

## Phase 3 — Recursive navigator (the core)

**Why:** this is the actual fix. Replace the one-shot picker with a bounded state machine.

- New module `src/navigator.py`: typed page roles (`landing|catalog|detail|register`),
  a work queue, depth/fetch caps, URL dedup.
- Role classifier: rules first (`crawl_link_score`, URL patterns), LLM only on ambiguity.
- Fan-out: a `catalog` page enqueues one `detail` target per camp link.
- Structured adapters become fast-path shortcuts the navigator calls on platform detection
  (same output shape, same verification gate) — not a separate code path.
- Keep `camp_navigator.py`'s LLM call, but demote it to "classify role / extract records,"
  not "pick the 3 best links."

**Exit:** on a flat multi-camp marketing site, every camp resolves to its own
`{info_url, register_url, verified}` row, not just the top 3.

---

## Phase 4 — Loosen the goal-fighting rules

**Why:** several current rules discard exactly the pages you want.

- `_rank_links_for_agent`: stop dropping cross-host non-platform links; down-weight instead.
- `adapter_llm`: keep an info page that has an on-page register CTA (mark `needs_trail` or
  `parent_ready` per signals) instead of rejecting "same marketing page."
- Add JSON-repair + one retry to the navigator LLM call; route navigation to the larger
  instruct model, reserve the 1B model for the fast binary classifier.

**Exit:** Jotform/Google-Form/custom register targets survive to verification; info-then-register
sites are kept.

---

## Phase 5 — Re-tune, measure, retire scaffolding

- Re-run the baseline towns; diff against Phase 0 snapshots.
- Confirm `parent_ready` count went up and false positives didn't.
- Collapse the now-redundant `b5_agent_nav_max_*` / `b5_trail_min_sessions` knobs into the
  navigator's depth/fetch caps.
- Update README + AGENT_SPEC to describe the navigator, not the old fallback.

**Exit:** single coherent traversal model; old picker + parallel-universe handling deleted.

---

## Sequencing notes

- Phases 0→2 are low-risk and independently shippable.
- Phase 3 is the big one; do it behind a `SETTINGS["b5_navigator_v2"]` flag so you can
  run old vs new side by side until parity is proven.
- Don't start Phase 5 deletions until the flag has run clean on ≥2 towns.
