"""Global resource profile — the cross-layer memory budget the W3W pilot crash
exposed (Jetsam vm-compressor-space-shortage on a 16GB Mac, 2026-06-12).

The codebase had per-subsystem caps (max_browsers, heavy-adapter semaphore) but
no single ceiling across Ollama + Playwright + parallel engine jobs. This module
is that ceiling. One profile is selected at import (RAM auto-detect, env
override) and applied to SETTINGS (config/settings.py) and ENGINE
(config_engine.py).

Select explicitly with FIREFLY_RESOURCE_PROFILE=16gb|32gb; otherwise total RAM
is detected and anything under 24 GB uses the conservative 16gb profile.
"""

from __future__ import annotations

import os

RESOURCE_PROFILES: dict[str, dict] = {
    # 16 GB unified memory (M2 Pro) — runs ALONGSIDE Cursor + Claude Code.
    # Goal: at most ONE Ollama model resident, one browser, no parallel jobs.
    "16gb": {
        # Ollama: collapse every role to ONE model so a second never loads.
        # gemma3:4b (~4-5GB resident) for categorizer quality; swap to
        # "gemma3:1b" (~1.5GB) here for an even lighter footprint.
        "ollama_single_model": "gemma3:4b",
        "ollama_keep_alive": "2m",          # was 30m — free RAM fast between phases
        "ollama_preload_models": False,     # never warm 1b+4b together
        "ollama_classify_concurrency": 1,
        "ollama_verify_concurrency": 1,
        # Playwright + crawl
        "engine_concurrency": 1,            # one provider at a time
        "max_browsers": 1,
        "b5_max_browsers": 1,
        "crawl_concurrency": 1,
        # Phase C enumeration ceiling (the real memory driver post-search)
        "gap_max_urls_per_round": 30,
        "gap_max_searches_per_round": 30,
        "gap_search_budget_per_town": 60,
        "max_details_per_provider": 25,     # MyRec/WebTrac render cap
        # Memory gates (MB free required before a heavy phase starts)
        "min_free_mb_phase_c": 3500,
        "min_free_mb_engine": 2500,
        "min_free_mb_crawl": 1800,
        "phase_c_enabled": True,
    },
    # 32 GB+ — closer to the original defaults; room for parallelism.
    "32gb": {
        "ollama_single_model": None,        # 1b fast + 4b verify may coexist
        "ollama_keep_alive": "30m",
        "ollama_preload_models": True,
        "ollama_classify_concurrency": 3,
        "ollama_verify_concurrency": 2,
        "engine_concurrency": 4,
        "max_browsers": 2,
        "b5_max_browsers": 2,
        "crawl_concurrency": 3,
        "gap_max_urls_per_round": 80,
        "gap_max_searches_per_round": 100,
        "gap_search_budget_per_town": 400,
        "max_details_per_provider": 60,
        "min_free_mb_phase_c": 2000,
        "min_free_mb_engine": 1500,
        "min_free_mb_crawl": 1000,
        "phase_c_enabled": True,
    },
}


def detect_profile() -> str:
    env = (os.environ.get("FIREFLY_RESOURCE_PROFILE") or "").strip().lower()
    if env in RESOURCE_PROFILES:
        return env
    try:
        import psutil

        total_gb = psutil.virtual_memory().total / (1024 ** 3)
        return "32gb" if total_gb >= 24 else "16gb"
    except Exception:  # noqa: BLE001 — psutil missing → assume the safe profile
        return "16gb"


ACTIVE_PROFILE: str = detect_profile()
PROFILE: dict = RESOURCE_PROFILES[ACTIVE_PROFILE]


def profile_value(key: str, default=None):
    return PROFILE.get(key, default)
