# Code Quality Assessment — Camp Link Discovery Engine

**Date:** 2026-07-06  
**Reviewer:** FRAIM code-quality-assessment  
**Overall Grade:** B

---

## Slide: Engine v3 is production-grade; legacy pipeline carries the debt

- `engine/` enforces a tested import boundary (zero violations) with clean subpackages: fetch, extract, validate, run, registry
- Engine modules follow R3–R6 constraints with strong docstrings and dataclass models
- Legacy stack (`phase_b/platforms.py` 2,065 lines, `orchestrator/run.py` 1,598 lines) dominates maintainability risk
- **Grade breakdown:** Engine A−, Legacy C+, Overall B

---

## Slide: Import boundary is real and enforced

- `tools/check_imports.py` AST-scans `engine/` for forbidden imports from pipeline packages
- `tests/test_engine_boundary.py` enforces in CI — **zero violations found**
- Engine is self-contained; pipeline bridges via `phase_c/engine_bridge.py` without re-importing enumeration
- One-directional check: pipeline may import engine, not vice versa (by design)

---

## Slide: Two monolithic files are the highest-priority refactor targets

| File | Lines | Issue |
|------|-------|-------|
| `phase_b/platforms.py` | 2,065 | 61 functions; all platform adapters in one file |
| `orchestrator/run.py` | 1,598 | Monolithic CLI + crawl orchestration |

**Recommendation:** Split `platforms.py` into `phase_b/platforms/{webtrac,myrec,sawyer,...}.py` mirroring `engine/extract/vendors/`. Thin `orchestrator/run.py` in favor of `unified_run.py` pattern.

---

## Slide: Duplication across engine and legacy stacks inflates fix cost

- `CHROME_LABELS` frozensets duplicated in `engine/validate/gate.py` and `phase_c/junk_audit.py`
- URL normalization duplicated: `shared/urls.py` vs `engine/fetch/urls.py`
- Dual fetch caches: `shared/fetch_cache.py` vs `engine/fetch/cache.py`
- Dual LLM clients: `engine/extract/llm.py` vs `shared/llm.py`
- Platform adapter logic exists in both `phase_b/platforms.py` and `engine/extract/vendors/`

**Recommendation:** Consolidate chrome detection and URL utils into `shared/` or finish engine migration.

---

## Slide: Phase layering is inverted in one critical dependency

- `phase_b/platforms.py` imports `phase_c.junk_audit.is_unusable_name`
- `phase_c/` also imports heavily from `phase_b/` — latent circular-import risk
- **Fix:** Move `is_unusable_name` / chrome detection to `shared/` so phase B does not depend on phase C

---

## Slide: Render policy diverges between engine and legacy pipeline

- Project rule R5.2: engine renders must **never use `networkidle`**
- `engine/fetch/render.py` correctly uses domcontentloaded + settle poll
- `phase_b/crawl.py` explicitly chooses `networkidle` for JS hosts
- `phase_d/hubs/*.py` also use networkidle patterns

**Impact:** Engine and pipeline follow different fetch policies; fixes may need dual edits until migration completes.

---

## Slide: No static analysis tooling is configured

- No `pyproject.toml`, `ruff`, or `mypy` config found
- Type hints strong in `engine/*` and newer modules; weak in `orchestrator/run.py`, `shared/store.py`
- No bare `except:` found across 206 Python files (excellent)
- ~30 files use broad `except Exception` — deliberate fail-open pattern, not silent swallowing

**Recommendation:** Add `ruff` + targeted `mypy --check-untyped-defs` on `engine/` only.

---

## Slide: Security posture is clean for credentials

- No hardcoded API keys, passwords, or tokens found in Python source
- API keys loaded via `.env` / environment variables (`.env.example` documents pattern)
- No security-critical findings in credential scanning

---

## Slide: Error handling follows deliberate fail-open design

- Extractor crashes → `Gap(reason="render_failed")` in `engine/run/runner.py`
- LLM failures return `None`; gate keeps row as `needs_review` (R3 compliant)
- Per-provider `asyncio.gather` isolation — one bad provider does not kill town run
- `gate_program()` in `engine/validate/gate.py` is thorough but ~240 lines — split into named check functions

---

## Slide: Prioritized remediation roadmap

| Priority | Action | Impact |
|----------|--------|--------|
| P0 | Split `phase_b/platforms.py` into per-vendor modules | High — reduces god-file risk |
| P0 | Resolve B↔C coupling (`junk_audit` import direction) | High — prevents circular imports |
| P1 | Consolidate `CHROME_LABELS` to single source | Medium — reduces drift |
| P1 | Add `ruff` + `mypy` on `engine/` | Medium — catches regressions |
| P2 | Thin `orchestrator/run.py`; standardize on `unified_run.py` | Medium — long-term |
| P2 | Complete engine migration; retire duplicate adapters | High — eliminates dual-stack edits |
| P3 | Un-export `_registrable_domain` from gate.py | Low — API hygiene |

---

## Slide: Dimension scorecard

| Dimension | Score | Notes |
|-----------|-------|-------|
| Architecture & boundaries | A− | Enforced import wall; clean engine layout |
| Engine v3 implementation | A− | Model code for the rest of repo |
| Legacy maintainability | C+ | God modules, inverted deps |
| Duplication / migration debt | C+ | Dual stacks during transition |
| Static tooling | C | No linter/type checker |
| Error handling | B+ | Deliberate fail-open; broad excepts |
| Security (credentials) | A | No hardcoded secrets |
| Tech debt markers | A | Essentially zero TODO/FIXME rot |
| **Overall** | **B** | Strong engine; legacy debt caps grade |
