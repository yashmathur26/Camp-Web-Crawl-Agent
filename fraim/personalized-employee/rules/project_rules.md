# Project Rules — Camp Link Discovery Engine

These rules supplement FRAIM's generic agent rules. They are specific to this repository and derived from `docs/engine_v3_docs/rules.md`. When a rule here conflicts with a task description, **stop and flag it** — do not silently pick one.

## Definition of done

1. No phase, task, or PR is complete until `python -m engine.eval --town lexington` has been run and its numbers recorded in the PR/commit description.
2. Never mark a roadmap/task checkbox done based on code "looking right."
3. Never write or modify a test to lock in broken behavior as a passing baseline.
4. If a change makes recall or precision go **down**, the change does not merge without an explicit human decision in the commit.

## Import boundary (R2)

1. `engine/` **never** imports from `src/`, `orchestrator/`, `shared/`, or `phase_a`–`phase_d`. Wanted old code is **ported** into `engine/`.
2. `src/` is frozen — do not refactor or extend it.
3. Run `python tools/check_imports.py` after engine changes; CI enforces this via `tests/test_engine_boundary.py`.

## LLM usage (R3)

1. The LLM extracts/structures information from rendered page text only. It never decides traversal, page role, or keep/drop.
2. Minimum input: 400 chars of page text. Thin/empty pages → `gap: empty`, not an LLM call.
3. Never invoke the LLM with a bare name as its only evidence.
4. **Fail open:** model unavailable, timeout, or unparseable output → item is **kept** and flagged `needs_review`, never dropped.
5. Log every LLM call: purpose, model, input summary, raw output, parsed result.

## Filtering and publishing (R4)

1. Keep/drop runs on **evidence** (dates, ages, price, catalog provenance) — never keyword-matching a name string.
2. Camp-scoped catalog items skip topical filtering; catalog scope is the evidence.
3. A row publishes only if `info_url` was fetched this run with ≥400 chars containing the program name.
4. Non-publishers land in `gaps.csv` with a diagnosis. Silent zeros are bugs.
5. Never publish navigation chrome, filenames, bare IDs, or empty names.
6. PDFs, images, and DocumentCenter assets are never programs.

## Fetching (R5)

1. One plain-HTTP path and one rendered path in `engine/fetch/`. No module rolls its own fetching.
2. Rendered fetches: fixed-wait settle, hard cap (default 20s), one attempt. **Never `networkidle`.**
3. Every fetch goes through the normalized-URL cache.
4. Per-provider budget is wall-clock seconds, not fetch count.
5. Media/asset URL classes are never enqueued as pages.

## Registry changes

1. The proposer writes `engine/registry/towns/<town>.proposals.yaml` — it **never** edits `towns/<town>.yaml` directly.
2. Humans promote approved entries per `engine/registry/REGISTRY_REVIEW.md`.
3. Validate after edits: `python -c "from engine.registry.schema import load_town; load_town('<town>')"`.

## Testing

- Default test command: `./venv/bin/python -m pytest -x -q`
- After every substantive change, run tests before committing.
- Prefer characterization/golden tests for vendor adapters over brittle string matches.

## Git and commits

- Only commit when explicitly asked.
- Do not push unless explicitly asked.
- One logical change per commit when the user requests commits.

## Scope discipline

- Minimize diff scope — do not refactor unrelated code.
- Do not add markdown docs unless requested.
- Match existing naming, types, and patterns in surrounding code.
