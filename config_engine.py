"""Engine v3 config — the complete knob list (R6.3: ≤15 knobs; every knob's
comment names the concrete failure it addresses)."""

ENGINE = {
    # Gov/SaaS sites 403 bot UAs (lca.edu returned 403 to the old crawler UA).
    "user_agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    # R4.3 invariant — the old pipeline published rows from 171-char shells.
    "min_info_chars": 400,
    # R5.2 — networkidle hung 6m43s on a MyRec shell; hard cap renders instead.
    "render_cap_s": 20,
    # Plain-path timeout; old pipeline's 3x-retries-on-timeout tripled hangs.
    "fetch_timeout_s": 25,
    # R5.4 — one hanging host must not eat the town run (wall-clock, not count).
    "provider_budget_s": 120,
    # Politeness between requests to the same host.
    "politeness_delay_s": 1.0,
    # Browser pool cap — unbounded Playwright instances OOM'd the old runs.
    "max_browsers": 2,
    # Generic path bounds — the old crawler wandered into MGH psychiatry pages.
    "generic_max_depth": 2,
    "generic_max_follows": 12,
    # Extraction-only LLM (R3).
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "llama3.2",
    # Cross-run cache reuse window; 0 disables persistence reuse.
    "cache_ttl_h": 24,
    # Phase 7 only — parallel provider jobs.
    "concurrency": 4,
}
