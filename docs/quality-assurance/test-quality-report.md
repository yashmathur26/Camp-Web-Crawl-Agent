---
reviewContext:
  subjectType: repository
  subjectLabel: Camp Link Discovery Engine
  reviewRef: test-quality-assessment-2026-07-06
  scopeSummary: Comprehensive test suite review covering standards compliance, coverage depth, R1 eval automation, vendor fixture discipline, and legacy vs engine v3 alignment.
  repoIdentifier: yashmathur26/Camp-Web-Crawl-Agent
  branchRef: engine-accuracy-roadmap-v3
  sourceInventory:
    - tests/
    - engine/eval/
    - engine/extract/vendors/
    - docs/engine_v3_docs/rules.md
    - tests/test_engine_boundary.py
quality:
  composite: 6.5
  grade: B-
  coverage:
    score: 6.5
    rationale: Engine package 79% line coverage; campbrain 32%, enrollsy 27%, active 33%; eval CLI __main__ 0%.
  testIntegrity:
    score: 6.0
    rationale: Dual gate paths; runner stubs all extractors; legacy networkidle locks conflict with R5.2.
  testDesign:
    score: 7.5
    rationale: Strong offline-first vendor tests with fixtures for 6/9 vendors; gate and fetch well designed.
  reliability:
    score: 9.0
    rationale: 442/443 pass consistently in ~63s; 0 failures.
  coaching: Add pytest integration test for engine.eval --town lexington with recall/precision floors — R1 definition of done must be automated.
overallGrade: B-
---

# Test Quality Assessment Report

## Executive Summary

The test suite scores **B−**. **442 of 443 tests pass** in ~65s with strong offline unit coverage for engine gate, fetch, and 6 of 9 vendor adapters. The critical gap is **R1**: `python -m engine.eval --town lexington` is not automated in pytest — definition of done remains manual. **campbrain** and **enrollsy** extractors have zero offline fixture tests (R7.2 violation). Legacy pipeline tests (~59 files) and dual gate systems dilute engine v3 signal.

**Presentation:** `docs/quality-assurance/test-quality-report-2026-07-06.pptx`

## Review Context

| Field | Value |
|-------|-------|
| Tests collected | 443 |
| Passed | 442 |
| Skipped | 1 (`test_baseline.py` — no Lexington B.5 output) |
| Test files | 74 |
| pytest.ini / conftest.py | None |
| CI workflow | None |

## Dimension Scorecard

| Dimension | Grade | Rationale | Next move |
|-----------|-------|-----------|-----------|
| Pass rate / stability | A | 442/443 pass, 0 failures | Maintain |
| Engine unit coverage | B+ | Gate, fetch, scoring, 6/9 vendors | Add campbrain + enrollsy fixtures |
| R1 eval as DoD | D | No town eval integration in pytest | Add eval CLI test with recall floors |
| Legacy vs v3 alignment | C− | Dual gates; networkidle legacy locks | Quarantine legacy gate tests |
| Fixture discipline (R7.2) | C | campbrain, enrollsy missing; daxko partial | Capture HTML fixtures + offline tests |
| Test infrastructure | C | No pytest config, no CI, no markers | Add pytest.ini + GitHub Actions |
| **Overall** | **B−** | Components tested; recall not proven | P0 eval automation |

## Evidence Highlights

1. **Eval gap:** `test_engine_eval.py` tests scoring math only — no `engine.eval --town lexington` integration.
2. **Vendor gaps:** campbrain and enrollsy have engine modules but zero offline tests.
3. **Dual gates:** `test_publish_gates.py` (legacy) vs `test_engine_phase1.py` (engine) test different implementations.
4. **Runner stub:** `test_runner_counts_match_csvs` stubs all extractors — never validates real recall.
5. **Anti-pattern remnant:** `characterization_locks.json` has orphaned `community_ed_session_count: 0`.

## Top Gaps / Risks

| Priority | Gap | Risk |
|----------|-----|------|
| P0 | No eval DoD in CI | Recall regressions ship undetected |
| P0 | campbrain/enrollsy untested | Production failures on new towns |
| P1 | Dual gate test paths | False confidence from legacy gate tests |
| P1 | No end-to-end town run test | Integration bugs between extract→gate→write |
| P2 | Legacy networkidle tests pass | Conflicts with engine R5.2 policy |

## Coaching Plan

1. **This week:** Add `test_engine_eval_integration.py` calling eval CLI with recall/precision floors.
2. **This week:** Capture campbrain + enrollsy HTML fixtures; add offline extractor tests.
3. **This sprint:** Add GitHub Actions: pytest + import boundary + eval.
4. **This sprint:** Mark legacy gate/networkidle tests `@pytest.mark.legacy`; exclude from engine CI.

## Source Inventory

- `tests/test_engine_phase1.py`, `tests/test_engine_fetch.py`, `tests/test_engine_vendor_golden.py`
- `tests/test_engine_boundary.py`, `tests/test_publish_gates.py`, `tests/test_baseline.py`
- `engine/eval/`, `engine/extract/vendors/`
- `tests/characterization_locks.json`
- `docs/engine_v3_docs/rules.md`
