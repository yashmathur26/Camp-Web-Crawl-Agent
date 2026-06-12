STATE = "MA"

SETTINGS = {
    # Free (no API key): "local_google" | "duckduckgo"
    # Paid: "serper" | "dataforseo" | "brave" | "serpapi" | "google_cse"
    "search_provider": "serper",
    "cost_per_query_usd": 0.001,
    "dataforseo_mode": "standard",
    "dataforseo_location_code": 2840,
    "dataforseo_language_code": "en",
    "dataforseo_poll_timeout_s": 180,
    "max_searches_per_run": 1000,
    "max_pages_per_source": 300,
    "max_links_per_domain_per_harvest": 80,
    "max_crawl_depth": 2,
    "stay_on_domain": True,
    "delay_seconds": 8.0,
    "crawl_concurrency": 3,
    "request_timeout": 30,
    "results_per_search": 10,
    "user_agent": "FindFireflyBot/0.1 (+contact: you@email.com)",
    "respect_robots_txt": True,
    "target_count": 5000,
    "phase_all_includes_c": False,
    "dry_run": True,
    # Ollama
    "ollama_base_url": "http://localhost:11434",
    # Part C Stage 0 (16GB sizing): gemma3:4b verify/auditor, gemma3:1b fast.
    "ollama_model": "gemma3:4b",
    "ollama_filter_model": "gemma3:4b",
    "ollama_fast_model": "gemma3:1b",
    "ollama_verify_model": "gemma3:4b",
    "ollama_classify_concurrency": 3,
    "ollama_verify_concurrency": 2,
    "ollama_preload_models": True,
    "agent_max_steps": 500,
    "ollama_validate_unknown": False,
    "ollama_validate_links": True,
    "ollama_validate_max_chars": 3000,
    "ollama_validate_max_fetches_per_source": 25,
    "ollama_validate_max_calls_per_source": 30,
    "ollama_validate_timeout_s": 45,
    "ollama_validate_fetch_delay_seconds": 1.5,
    "geo_filter_crawl": True,
    "ollama_keep_alive": "30m",
    "ollama_session_max_chars": 6000,
    "ollama_session_timeout_s": 60,
    "focused_max_pages_per_camp_host": 8,
    "focused_max_depth": 3,
    "focused_delay_seconds": 1.5,
    "focused_stop_on_catalog": True,
    "ollama_link_follow": True,
    "ollama_link_follow_max_per_source": 6,
    "ollama_link_follow_timeout_s": 20,
    "program_focus": "youth_summer",
    "filter_to_focus": True,
    # roadmap2 Phase 5 — validation gate: only rows passing validate_session
    # reach the deliverable CSV; the rest go to camp_sessions_quarantine.csv.
    "b5_validation_gate": True,
    # roadmap2 Phase 6 — efficiency + verdict policy.
    "b5_fetch_cache": True,          # process-level dedupe of identical fetches
    "b5_cross_provider_dedupe": True,  # merge funnel duplicates across providers
    # MyRec detail pages render their cart via JS we don't drive, so MyRec can't
    # honestly reach parent_ready on the crawl path. Ship it as needs_js (a
    # render/Firecrawl confirm pass can upgrade it later) rather than guessing.
    "b5_myrec_verdict": "needs_js",
    # roadmap2 Phase 3: evidence-based filtering — recover real youth programs
    # whose names lack "camp/summer" keywords via the instruct-model tie-breaker,
    # failing OPEN (keep) on camp-context ambiguous rows when the model is down.
    "ollama_focus_verify": True,
    "b5_focus_verify_fail_open": True,
    "ollama_focus_verify_max_per_source": 45,
    "ollama_focus_verify_consecutive_drop_limit": 20,
    "ollama_focus_verify_timeout_s": 20,
    # Tiered crawl profiles (Phase B efficiency)
    "crawl_tier_profiles": {
        "preferred": {
            "max_pages": 8,
            "max_depth": 3,
            "delay_seconds": 1.5,
            "focused": True,
            "stop_on_catalog": True,
            "ollama_link_follow": True,
        },
        "camp_host": {
            "max_pages": 12,
            "max_depth": 3,
            "delay_seconds": 2.0,
            "focused": True,
            "stop_on_catalog": True,
            "ollama_link_follow": True,
        },
        "directory": {
            "max_pages": 40,
            "max_depth": 2,
            "delay_seconds": 3.0,
            "focused": False,
            "stop_on_catalog": False,
            "ollama_link_follow": False,
        },
        "unknown": {
            "max_pages": 10,
            "max_depth": 2,
            "delay_seconds": 1.5,
            "focused": True,
            "stop_on_catalog": True,
            "ollama_link_follow": False,
        },
    },
    # B.5 heavy adapter isolation
    "b5_heavy_adapter_concurrency": 1,
    "b5_default_concurrency": 1,
    "b5_max_browsers": 2,
    "b5_navigator_v2": False,
    "b5_nav_max_depth": 3,
    "b5_nav_max_fetches": 25,
    # roadmap2 Phase 1 — never publish chrome/button/menu text as a camp name.
    "b5_name_integrity": True,
    # roadmap2 Phase 2 — render JS/portal pages before reading them.
    # Hosts that need Playwright networkidle for *all* fetch kinds (their content
    # loads via JS after domcontentloaded). Substring match on the URL.
    "b5_render_networkidle_hosts": (
        "hisawyer",
        "sawyer",
        "active.com",
        "activecommunities",
        "enrollsy",
        "myrec",
        "sgasoftware",
        "perfectmind",
        "campbrain",
        "daxko",
        "jackrabbit",
        "veracross",
    ),
    # A render returning fewer than this many chars on a JS host is "thin" —
    # retry once with a settle before believing the page is empty.
    "b5_render_thin_chars": 400,
    "b5_render_settle_seconds": 1.2,
    # Persist rendered page text to data/<town>/phase_b5/captured/ (capture-then-
    # extract). Off by default; Phase 7 turns it on for the cutover run.
    "b5_capture_pages": False,
    "b5_agent_navigation": True,
    "b5_agent_nav_link_cap": 60,
    "b5_agent_nav_max_catalog_fetches": 3,
    "b5_agent_nav_max_register_fetches": 2,
    "b5_agent_nav_timeout_s": 90,
    "b5_trail_before_llm": False,
    "b5_trail_pages": 12,
    "b5_trail_min_sessions": 3,
    "b5_broad_discovery": False,
    "b5_discovery_max_candidates": 50,
    "b5_discovery_max_fetches": 8,
    "b5_discovery_path_probes": 10,
    "b5_trace_verbose": True,
    # Phase B.6 registration trail
    "trail_max_pages": 12,
    "trail_max_depth": 4,
    # Phase A optional LLM judge for unknown hits
    "phase_a_llm_judge": False,
    # Phase P parent enrollment verification
    "parent_verify_concurrency": 4,
    "parent_verify_max_llm": 80,
    "parent_verify_fetch_timeout_ms": 15000,
    "parent_verify_networkidle_hosts": ("myvscloud", "daxko"),
    "parent_verify_confidence_threshold": 0.75,
    # Task 4.2 publish gates — only verified rows reach the parent deliverable;
    # everything else is HELD in phase_p/review_queue.csv, never deleted.
    "publish_require_verify": True,
    "publish_allowed_verdicts": ["parent_ready", "brochure_only"],
    "season_year": 2026,
    # Phase C agentic gap fill
    "gap_rounds_default": 2,
    "gap_max_searches_per_round": 100,
    "gap_hole_cache_days": 7,
    "gap_fallback_taxonomy": False,
    # Part C: exhausted-state TTL, regional sharing radius, per-town budgets.
    "gap_hole_exhausted_days": 60,
    "gap_share_radius_miles": 10,
    "gap_share_radius_rare_miles": 15,
    "gap_search_budget_per_town": 400,
}
