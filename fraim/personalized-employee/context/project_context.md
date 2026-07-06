# Project Context — Camp Link Discovery Engine

## Purpose

Discovers **summer camp primary-source URLs** for Middlesex County, MA (~53 towns): recreation departments, community education catalogs, YMCA/JCC pages, and local providers. Output is parent-ready session data (info URLs, register URLs, dates, ages, prices) for downstream Firecrawl/taxonomy stages.

**Not in scope:** aggregators (ActivityHero, Macaroni Kid, Kidvoyage, Yelp) or after-school program guides.

## Stack

- **Language:** Python 3.11
- **Key deps:** crawl4ai, playwright/chromium, ddgs, ollama (optional LLM filter), rapidfuzz, tldextract
- **Setup:** `python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
- **Browsers:** `crawl4ai-setup` or `python -m playwright install chromium`

## Pipeline stages

The unified runner executes stages in order **A → B → engine → D → C**:

| Directory | Stage | Role |
|-----------|-------|------|
| `orchestrator/` | — | CLI entrypoints (`run.py`, `unified_run.py`) |
| `phase_a/` | A | Search / discovery → candidate URLs |
| `phase_b/` | B | Crawl + harvest validated candidates → sessions |
| `engine/` | engine | v3 extraction engine (vendor adapters + generic extractor + publish gate); `python -m engine.run` |
| `phase_d/` | D | Hub adapters (camp-invention, configio, idtech) + US Sports Camps |
| `phase_c/` | C | Registry, categorization, agentic gap-fill, deliverables |
| `shared/` | — | Cross-stage utilities (urls, cache, store, data_layout, llm, geo) |
| `config/`, `config_engine.py` | — | Settings, towns, keywords, sources, hub registry |

The **engine never imports the discovery pipeline** (enforced by `tools/check_imports.py`). Shared old code is *ported* into `engine/`, not imported.

## Engine v3 product contract

For any input town, produce four CSVs:

- `providers.csv` — provider metadata
- `programs.csv` — program-level rows with `info_url`
- `sessions.csv` — session-level rows with dates, ages, price, verdict
- `gaps.csv` — providers that did not publish, with diagnosis

Primary value: **`info_url`** — the content-rich page right before registration.

**Verdicts:** `parent_ready`, `info_confirmed`, or `gap:*`. Publish only when `info_url` was fetched and yielded ≥400 chars containing the program name.

## Town registry

Hand-curated provider list per town at `engine/registry/towns/<town>.yaml`. The proposer writes `*.proposals.yaml`; humans promote to `towns/<town>.yaml`. Review flow: `engine/registry/REGISTRY_REVIEW.md`.

**Current towns:** Lexington, Burlington, Waltham, Watertown.

## Key docs

| Doc | Purpose |
|-----|---------|
| `README.md` | Setup, search providers, usage |
| `docs/engine_v3_docs/rules.md` | Hard constraints (read first) |
| `docs/engine_v3_docs/implementation_plan.md` | Technical design |
| `docs/engine_v3_docs/roadmap.md` | Sequencing |
| `docs/engine_v3_docs/AGENT_EXECUTION_PLAN.md` | Agent task workflow |
| `docs/HUB_ADAPTER_ROADMAP.md` | National hub adapters (Camp Invention, Skyhawks, iD Tech) |

## Common commands

```bash
# Full pipeline
python -m orchestrator.unified_run

# Engine only (per town)
python -m engine.run --town lexington

# Eval (definition of done)
python -m engine.eval --town lexington

# Tests
./venv/bin/python -m pytest -x -q

# Import boundary check
python tools/check_imports.py
```

## Search providers

Configured in `config/settings.py`. Free defaults: `local_google`, `duckduckgo`. Paid options: Serper, DataForSEO, Google CSE. Optional `.env` for API keys (see `.env.example`).

## Optional Ollama

Phase B harvest uses a local LLM camp filter by default. Disable with `--no-llm-validate` if Ollama is not running. Models configured in `config/settings.py`.

## Repository

- GitHub: `yashmathur26/Camp-Web-Crawl-Agent`
- Default branch: `main`
- Active development branch (at onboarding): `engine-accuracy-roadmap-v3`
