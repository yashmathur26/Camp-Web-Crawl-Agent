# RULES.md — Engine v3 Constraints

These are hard constraints for any coding agent working on this repo. They exist because
every one of them was violated by the previous pipeline and caused a documented, costly
failure. Violating a rule is a bug even if the code "works." When a rule conflicts with a
task, STOP and flag it — do not silently pick one.

Read `roadmap.md` for sequencing, `implementation_plan.md` for design,
`task.md` for the current work unit.

---

## R1 — The eval is the definition of done

1. No phase, task, or PR is "complete" until `python -m engine.eval --town lexington`
   has been run and its numbers recorded in the PR/commit description.
2. Never mark a roadmap/task checkbox done based on the code "looking right." The previous
   pipeline marked the CommunityEd fix, networkidle fix, funnel dedupe, and fail-open
   tie-breaker complete while all four remained broken in production logs.
3. Never write or modify a test to lock in broken behavior as a passing baseline
   (the old `community_ed_session_count == 0` anti-pattern). Tests assert the contract.
4. If a change makes recall or precision go DOWN, the change does not merge —
   no exceptions without an explicit human decision recorded in the commit.

## R2 — Import boundary

1. `engine/` NEVER imports from `src/`. Wanted old code is PORTED: copied into `engine/`,
   given its own test, owned. CI fails the build on `from src` / `import src` inside
   `engine/`.
2. `src/` is frozen. Do not refactor, "improve," or extend it. It exists only for
   baseline comparison until Phase 8 deletes it.
3. Fixtures (`tests/fixtures/`), ground truth, and the `data/` layout are shared data and
   may be read by both.

## R3 — LLM usage (the perception-only rule)

1. The LLM is called ONLY to extract/structure information from rendered page text.
   It never decides traversal, never classifies a page's role, never makes keep/drop
   decisions.
2. Minimum input: the LLM is never invoked with fewer than 400 chars of page text.
   A thin/empty page is a `gap: empty`, not an LLM call. (The old pipeline asked the
   model to classify a 0-char page; it hallucinated "a catalog listing camps with names,
   ages, dates" and the code believed it.)
3. The LLM never receives a bare name as its only evidence. "Is 'Badminton' a youth
   summer camp?" is unanswerable; do not ask it.
4. FAIL OPEN: model unavailable, timeout, or unparseable output → the item is KEPT and
   flagged (`needs_review`), never dropped. A dropped camp is invisible forever; a flagged
   one is recoverable downstream.
5. Every LLM call logs: purpose, model, input summary, raw output, parsed result.

## R4 — Filtering and publishing

1. Keep/drop decisions run on EVIDENCE extracted from content (dates, ages/grades, price,
   camp-scoped catalog provenance) — never on keyword-matching a name string.
2. Items from a camp-scoped catalog (WebTrac `type=CAMP`, an ACTIVE camp season, a
   `/lexplorations/` class listing) skip topical filtering entirely; catalog scope IS the
   evidence.
3. A row publishes ONLY if its `info_url` was fetched in this run and yielded ≥ 400 chars
   of rendered text containing the program name (`content_chars` recorded on the row).
   No exceptions: not for "the URL pattern looks right," not for platform IDs.
4. Everything that doesn't publish lands in `gaps.csv` with a diagnosis
   (`needs_adapter | render_failed | blocked | empty | needs_review`). Silent zeros are
   bugs. Junk rows are bugs. There is no third state.
5. Never publish a row whose name is navigation chrome, a filename, a bare ID, or empty.
6. PDFs, images, and DocumentCenter-style assets are never programs. They may be recorded
   as attachments on a program, nothing more.

## R5 — Fetching

1. There is exactly ONE plain-HTTP fetch path and ONE rendered fetch path
   (`engine/fetch/`). No module rolls its own fetching.
2. Rendered fetches: fixed-wait settle policy, hard cap (default 20s), ONE attempt.
   Never `networkidle` (it hangs forever on chatty hosts — MyRec cost 6m43s for a
   171-char shell). Retries are for network errors only, never for timeouts.
3. Every fetch goes through the normalized-URL cache. The same URL is fetched at most
   once per run regardless of which provider reached it.
4. Per-provider budget is WALL-CLOCK seconds, not fetch count. A hanging host cannot eat
   the town run.
5. Media/asset URL classes (.pdf, .png, .jpg, .docx, /DocumentCenter/, /uploads/) are
   never enqueued as pages.
6. Respect robots.txt and per-host politeness delays; identify with the configured UA.
7. Vendor extractors prefer the vendor's data path (JSON API, embedded JSON,
   server-rendered listing rows) over rendering. A browser is the last resort, not the
   default.

## R6 — One of everything

1. One publish gate (`engine/validate/gate.py`). One output writer. One set of counts.
   If the log says "26 saved" the CSV contains 26 rows — the old pipeline printed
   "0 published" and "+26 rows" for the same provider because two writers disagreed.
2. One data model (`engine/model.py`): Provider → Program → Session, with provenance on
   every row. No parallel session dict shapes.
3. Config lives in `config_engine.py`, capped at ~15 knobs. Adding a knob requires a
   comment naming the concrete failure it addresses. Do not port the old settings sprawl.

## R7 — Code hygiene

1. No committed reasoning narration, TODO-streams, or "let me trace..." comments. If you
   are unsure logic is correct, write the test that proves it before committing.
2. Every vendor extractor ships with a captured fixture (real response saved to
   `tests/fixtures/<vendor>/`) and a test that runs offline against it.
3. Functions that talk to the network are isolated behind `engine/fetch/` so all logic is
   testable offline.
4. Keep the plain-English narration log (one block per provider: tried X, found Y,
   gapped Z because W) — it is the primary debugging artifact.

## R8 — Scope discipline

1. Do not build an extractor for a vendor until it appears in `gaps.csv` as
   `needs_adapter` for ≥ 2 providers OR blocks a ground-truth program in a pilot town.
2. Do not add discovery/search features before Phase 6. The registry is hand-curated for
   pilot towns; that is intentional.
3. Do not optimize (parallelism, caching layers beyond R5.3, model pooling) before
   Phase 7. Correctness and recall first.
4. When a task is ambiguous, prefer the smaller interpretation and leave a note in the PR
   rather than expanding scope.
