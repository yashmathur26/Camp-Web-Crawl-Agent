W3W PILOT — Waltham, Woburn, Watertown
=====================================

Isolated test run. All pipeline artifacts are under:
  data/<town>/phase_a|phase_b|engine|phase_gap/
  registry/<town>.yaml
  logs/pilot_run.log

Final deliverables:
  FINAL_sessions.csv
  FINAL_sessions.txt
  RUN_SUMMARY.json

================================================================
SAFE RELAUNCH ON 16GB (after the 2026-06-12 Jetsam crash fix)
================================================================
The pilot auto-applies the 16gb resource profile (one Ollama model, one
browser, concurrency 1, Phase-C URL caps, memory gates). For extra safety,
restart Ollama with a single worker first:

  export OLLAMA_MAX_LOADED_MODELS=1
  export OLLAMA_NUM_PARALLEL=1
  ollama stop 2>/dev/null; pkill llama-server 2>/dev/null; sleep 2; ollama serve &

  cd "/Users/yashmathur/Desktop/firefly web scraper"
  ./venv/bin/python pilot/w3w_test/run_pilot.py --resume --gap-rounds 1 --gap-searches 30

--resume skips towns whose Phase C is already done (Waltham), so a crash costs
minutes, not hours. Memory usage is traced to logs/memory_trace.jsonl.
A lighter model is available: set ollama_single_model to "gemma3:1b" in the
"16gb" profile in config/resource.py (faster, ~1.5GB, slightly lower quality).
