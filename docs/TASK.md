# TASK.md — B.5 Navigator Refactor

Work top-to-bottom. Each task has a clear Definition of Done (DoD). Do not start a task
until the one above it is green. Reference `IMPLEMENTATION_PLAN.md` for the design and
`RULES.md` for constraints. Tasks map to roadmap phases.

---

## P0 — Safety net

- [x] **P0.1** Capture baseline B.5 output into `data/_baseline/<town>/`. Commit it.
  (`baseline.json` + `camp_sessions.csv` per town; Lexington 21 providers / 78 sessions,
  Burlington 14 providers / 46 sessions.)
- [x] **P0.2** Save real HTML fixtures (crawl path) for WebTrac, MyRec, CommunityEd,
  and a generic marketing site under `tests/fixtures/<platform>/`.
- [x] **P0.3** Characterization tests in `tests/test_characterization_*.py` lock
  `detect_platform`, structured adapters, `enumerate_provider`, and `enrollment_signals`
  against captured fixtures (fetch mocked only).
  - DoD: `pytest` green; baseline JSON/CSVs and fixtures committed.

---

## P1 — Three-node schema

- [x] **P1.1** Add `info_url: str = ""` and `details_text: str = ""` to `make_session`
  in `src/platforms.py`. (`details_text` defaults ""; both fields on every session dict.)
- [x] **P1.2** Add `info_url` to `SESSION_CSV_COLUMNS` and any writer that lists columns
  (`session_quality.py`, deliverables). (`info_url` after `register_url`; writers use `SESSION_CSV_COLUMNS`.)
- [x] **P1.3** Set `info_url` in adapters that already know the detail page (WebTrac item,
  MyRec program_details); leave "" elsewhere. (`info_url=register_url` for WebTrac/MyRec; `""` for all other adapters.)
  - DoD: baseline run reproduces identical camps + a new empty `info_url` column;
    P0 tests still green.

---

## P2 — Inline verification gate

- [x] **P2.1** Refactor `enrollment_signals.py` so the core check is a pure function
  `verify_registrable(url: str, html: str) -> EnrollmentSignals` (no phase coupling).
- [x] **P2.2** Add a `networkidle` fetch option and use it for `register`/`portal` targets
  in the navigator fetch path.
- [x] **P2.3** Let the navigator set `parent_verdict` / `parent_can_register` directly when
  it has the register page in hand. Phase P becomes batch re-verify only.
  - DoD: a camp reaches `parent_ready` only after its register page was fetched and signals
    confirmed cart/price/CTA. Unit test with a fixture proves it.

---

## P3 — Recursive navigator (core)

- [ ] **P3.1** Create `src/navigator.py` with a `PageRole` enum
  (`LANDING|CATALOG|DETAIL|REGISTER`) and a `NavNode` dataclass
  (`url, role, depth, parent_url`).
- [ ] **P3.2** Implement `classify_role(url, html, links)` — rules first via existing
  `crawl_link_score` / `is_registration_platform_url` / `is_camp_catalog_url`; LLM only
  when ambiguous.
- [ ] **P3.3** Implement the bounded traversal loop: work queue, `max_depth=3`,
  `max_fetches_per_provider`, dedup on `normalize_url`. Catalog → enqueue each camp as
  DETAIL; detail → find register link, enqueue as REGISTER; register → verify + emit.
- [ ] **P3.4** Make structured adapters fast-path shortcuts: on platform detection, call
  the adapter, wrap its results into `NavNode`s/sessions, run them through the SAME
  verification gate. Remove the parallel handling in `agent_navigate_provider`.
- [ ] **P3.5** Wire `enumerate_provider` to call the navigator behind
  `SETTINGS["b5_navigator_v2"]` (default off). Old path stays callable.
  - DoD: with the flag on, a flat multi-camp marketing-site fixture yields one row per camp
    with populated `info_url` + `register_url` + verdict — not just 3.

---

## P4 — Loosen goal-fighting rules

- [ ] **P4.1** `_rank_links_for_agent`: stop `continue`-dropping cross-host non-platform
  links; keep them with a lower score so the model still sees them.
- [ ] **P4.2** `adapter_llm`: keep an info page that has an on-page register CTA (verify via
  `verify_registrable`) instead of rejecting "only link is the same marketing page."
- [ ] **P4.3** Add JSON-repair + one retry to the navigator LLM call. Route navigation to
  the larger instruct model (`ollama_verify_model`); keep the 1B model only for the fast
  binary classifier.
- [ ] **P4.4** Fix the `seen_regs` dedup bug (catalog URLs and register URLs share one set).
  - DoD: fixture with an external Jotform/Google-Form register link survives to verification;
    info-then-register site is kept; no double-fetch of the same catalog URL.

---

## P5 — Cut over, measure, clean up

- [ ] **P5.1** Re-run baseline towns with `b5_navigator_v2=true`; diff vs `data/_baseline/`.
- [ ] **P5.2** Confirm `parent_ready` count up, false positives not up (manual spot-check 15).
- [ ] **P5.3** Flip the flag default to true; collapse `b5_agent_nav_max_*` and
  `b5_trail_min_sessions` into navigator caps.
- [ ] **P5.4** Delete the old `_pick_agent_urls` one-hop path and update README / AGENT_SPEC.
  - DoD: one traversal model in the tree; docs match reality; tests green.

---

## Done-everywhere checklist (every PR)

- P0 characterization tests still pass.
- New behavior is behind or past the `b5_navigator_v2` flag, never silently changing the
  old path.
- No structured adapter lost coverage (compare against baseline).
