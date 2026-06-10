# RULES.md — Constraints for the coding agent

These are guardrails for any agent modifying this repo during the B.5 refactor.
Violating them is how the valuable parts get broken. Read before editing.

---

## Architecture rules

1. **Deterministic code controls traversal; the LLM only does perception.**
   The control flow (which page to visit, when to stop, how to fan out) lives in Python.
   The model's only jobs are: classify a page's role, and extract camp records as JSON.
   Never ask the model to "decide where to go next" as freeform reasoning.

2. **Structured adapters are sacred.** WebTrac/MyRec/WooCommerce adapters and
   `detect_platform` encode hard-won edge cases. Do not rewrite them in this refactor.
   They become fast-path shortcuts the navigator calls — same output shape, same
   verification gate. If an adapter must change, add a fixture test first.

3. **One traversal model, not two.** The end state has a single navigator. Do not leave the
   old `_pick_agent_urls` one-hop picker running in parallel with the new loop past P5.
   Until then, the new path lives behind `SETTINGS["b5_navigator_v2"]`.

4. **Three-node reality.** A camp has up to three URLs of interest: `info_url` (details),
   `register_url` (cart/checkout), and `source_url`. Never collapse info and register back
   into one field.

5. **Verify where you fetch.** Registrability is decided by `verify_registrable` at the
   moment the register page is in hand — not asserted from a URL pattern, and not deferred
   to a later phase.

---

## Behavioral guardrails

6. **No regressions against baseline.** Every change is diffed against `data/_baseline/`.
   A drop in any provider's session count is a failure to explain, not accept.

7. **Bound everything.** The navigator must have hard caps: `max_depth`, max fetches per
   provider, URL dedup on `normalize_url`. No unbounded recursion or crawl. A single
   provider must never block the whole run (respect the heavy-adapter semaphore pattern).

8. **Fail open on the model, not on the data.** If Ollama errors or returns bad JSON:
   retry once, repair, then fall back to rules — never silently emit zero sessions for a
   provider that rules could have handled.

9. **Don't widen scope.** This refactor is the navigator, schema, and verification seam.
   Do not "improve" discovery (Phase A/B), geo filtering, or search providers in the same
   PRs. File separate issues.

10. **Respect cost/latency intent.** Cheap layers first: rules → cache → adapter → LLM.
    Never add an LLM call where a regex already decides. Reserve the small (1B) model for
    the fast binary classifier; navigation/extraction uses the larger instruct model.

---

## Code hygiene

11. **Flag-gate risky changes.** New traversal behavior is off by default until parity is
    proven on ≥2 towns.
12. **Fixtures over live crawls in tests.** Tests run against saved HTML, not the network.
13. **Small PRs, one task each.** Match the units in `TASK.md`. Each PR keeps P0 tests green.
14. **Logging stays parent-legible.** The `session_log` narration ("AI will pick which pages
    list camps and where parents register") is a feature — keep traversal decisions logged
    in plain language.

---

## Definition of "done" for the whole effort

- A generic multi-camp marketing site produces one verified row per camp, each with its own
  `info_url` and `register_url`.
- `parent_ready` means a human-checkable register affordance was actually observed.
- Structured platforms still enumerate every item (no adapter regression).
- One navigator, documented, with the old picker removed.
