# Registry review flow (Phase 6, task 6.2)

The proposer writes `towns/<town>.proposals.yaml` — it NEVER touches
`towns/<town>.yaml`. A human (~10–30 min per town) promotes entries:

1. Generate: feed candidate seed URLs (search results, town rec page, prior
   lists) to `engine.registry.proposer.propose_town(town, state, urls)`.
2. Review each proposal: open the seed; confirm it is a real local provider
   (not an aggregator/blog); check the fingerprinted `vendor`/`org_id` against
   the registration link a parent would click.
3. Promote approved entries into `towns/<town>.yaml` (same fields; add
   `aliases` for funnel hosts, `notes` for caveats). Delete rejects.
4. Validate: `python -c "from engine.registry.schema import load_town; load_town('<town>')"`.
5. Run: `python -m engine.run --town <town>`, then eval if ground truth exists.

Task 6.3 [HUMAN]: run this flow on a fresh town and record proposal coverage
vs that town's ground truth (target ≥80%).
