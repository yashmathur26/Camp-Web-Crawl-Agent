# Test Quality Assessment — Camp Link Discovery Engine

**Date:** 2026-07-06  
**Reviewer:** FRAIM test-quality-assessment  
**Overall Grade:** B−

---

## Slide: 443 tests pass but R1 eval is not automated

- **442 passed, 1 skipped** in ~65s (`./venv/bin/python -m pytest -q`)
- Skipped: `test_baseline.py::test_lexington_provider_floors` (no Lexington B.5 output in fresh clone)
- **Critical gap:** No pytest invokes `python -m engine.eval --town lexington` — R1 definition of done is manual only
- Suite proves components work in isolation, not that Lexington recall meets ground truth

---

## Slide: Engine unit coverage is strong for core primitives

| Area | Coverage | Test files |
|------|----------|------------|
| Publish gate | Excellent | `test_engine_phase1.py`, `test_engine_vendor_golden.py` |
| Fetch (HTTP, render, cache, budget) | Excellent | `test_engine_fetch.py` |
| Vendor adapters (6/9) | Good | `test_engine_vendors_wave1/2.py`, golden tests |
| Import boundary (R2) | Enforced | `test_engine_boundary.py` |
| LLM fail-open (R3) | Good | `test_engine_llm_verifier.py`, `test_engine_generic.py` |
| Scoring math | Good | `test_engine_eval.py` |

---

## Slide: Two vendor extractors have zero offline tests (R7.2 violation)

| Vendor | Engine module | Fixture | Tests |
|--------|--------------|---------|-------|
| campbrain | ✅ exists | partial | **None** |
| enrollsy | ✅ exists | **None** | **None** |
| daxko | ✅ exists | ❌ | 1 swim-test filter only |

R7.2 requires every vendor extractor to ship with captured fixture + offline test. **campbrain** and **enrollsy** are critical gaps.

---

## Slide: Dual gate systems create false confidence

- Engine gate: `engine/validate/gate.py` — well tested
- Legacy gate: `phase_c.deliverables.apply_publish_gates` + `phase_c.junk_audit.validate_session`
- R6 mandates **one gate** — tests cover two divergent implementations independently
- `test_publish_gates.py` and `test_validation_gate.py` test legacy path; may not reflect production engine behavior

**Recommendation:** Deprecate or quarantine legacy gate tests; align suite with single `engine.validate.gate`.

---

## Slide: Runner integration test stubs all extractors

- `test_engine_phase1.py::test_runner_counts_match_csvs` stubs **all** extractors → always 21 `needs_adapter` gaps
- Validates CSV count consistency only — never tests real extraction recall
- **Missing:** End-to-end town run for at least one provider (WebTrac or MyRec) through extract → gate → write → eval

---

## Slide: Legacy pipeline tests dilute engine v3 signal

- ~74 test files total; ~59 test legacy `phase_b`/`phase_c` pipeline (frozen per R2)
- `test_fetch_wait.py` and `test_render.py` lock **networkidle** behavior that R5.2 forbids for engine
- `test_characterization_adapters.py` locks MyRec session count at 89 (whole catalog, not summer-filtered contract)
- Orphaned lock: `characterization_locks.json` has `community_ed_session_count: 0` with no test (deleted anti-pattern remnant)

---

## Slide: Test infrastructure lacks project scaffolding

| Expected | Present? |
|----------|----------|
| `pytest.ini` / `[tool.pytest]` | ❌ |
| Root `conftest.py` | ❌ |
| Shared auto-loaded fixtures | ❌ (manual import of `conftest_characterization.py`) |
| `@pytest.mark.integration` / `@pytest.mark.slow` | ❌ |
| CI workflow running pytest | ❌ (no `.github/workflows`) |
| `pytest` pinned in requirements | ❌ (in venv but unpinned) |

---

## Slide: Registry and eval coverage gaps

**Registry (partial):**
- Schema validation, Lexington GT host ⊆ registry — covered
- Proposer fingerprint + proposals-only — covered
- **Gap:** No test that registry YAML fields drive campbrain/enrollsy extractors correctly

**Eval (weak):**
- Fuzzy matcher, date windows, scoring math — unit tested
- Golden vendor tier routing — 100% in fixtures
- **Missing:** Eval CLI `--compare`, history write, recall/precision floors against ground truth

---

## Slide: Mission-critical scenarios lacking coverage (R1–R8)

| Rule | Requirement | Status |
|------|-------------|--------|
| R1 | Eval is definition of done | ❌ Not in pytest |
| R1.4 | Recall/precision regression blocks merge | ❌ No automated floor |
| R6 | One gate, one writer | ⚠️ Dual paths tested |
| R7.2 | Every vendor → fixture + offline test | ❌ campbrain, enrollsy |
| R5 | No networkidle in engine fetch | ⚠️ Legacy tests still pass networkidle |

---

## Slide: Prioritized remediation roadmap

| Priority | Action |
|----------|--------|
| P0 | Add eval CLI integration test: `engine.eval --town lexington` with recall/precision floors |
| P0 | Add campbrain + enrollsy offline fixture tests |
| P1 | End-to-end town run test (1 real provider, no extractor stub) |
| P1 | Deprecate/quarantine legacy gate tests; align with `engine.validate.gate` |
| P1 | Add CI workflow: pytest + import boundary + eval |
| P2 | Remove/update networkidle legacy tests or mark `@pytest.mark.legacy` |
| P2 | Clean `characterization_locks.json`; revisit MyRec 89-count lock |
| P2 | Add root `conftest.py`, `pytest.ini`, pin pytest in dev requirements |
| P3 | Daxko full ProgramDetail HTML fixture test |

---

## Slide: Dimension scorecard

| Dimension | Grade | Rationale |
|-----------|-------|-----------|
| Pass rate / stability | A | 442/443 pass, 0 failures |
| Engine unit coverage | B+ | Gate, fetch, scoring, 6/9 vendors |
| R1 eval as DoD | D | Scoring unit tests only; no town eval integration |
| Legacy vs v3 alignment | C− | Dual gates; legacy networkidle locks |
| Fixture discipline (R7.2) | C | 2 vendors missing; daxko partial |
| Test infrastructure | C | No pytest config, no CI, no markers |
| **Overall** | **B−** | Broad passing suite; mission-critical eval gap |
