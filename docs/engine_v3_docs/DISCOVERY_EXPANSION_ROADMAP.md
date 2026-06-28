# Discovery Expansion Roadmap — population-scaled budget + institution discovery

New initiative on top of the Engine v3 phases (`roadmap.md`). Three threads, agreed
with the operator (W3W feedback rounds):

1. **Population-scaled, adaptive per-town search budget** (Phase A + Phase C).
2. **College / university camp discovery** (hybrid sourcing).
3. **School camp discovery** — private/prep, public high, public elem/middle (district
   level), and trade/vocational schools.

Guiding rule (operator, standing): **no hard-coded per-domain fixes; make the rule
keyword/structure based so the next town/site is handled without a code change.** Output
must stay slop-free — every discovered row still passes the one engine gate
(`engine/validate/gate.py` + `engine/validate/noncamp.py`).

---

## Thread 1 — Smart per-town search budget

Today: Phase A runs a flat 53 keyword searches for **every** town; Phase C is capped at a
flat `--gap-searches 40`. No size awareness.

**Target:** each town derives its own budget from three signals, biased toward *more*
searches (operator: "more is beneficial for both A and C"), with an adaptive stop so we
never waste searches on a dry town.

### Budget math (decided)
```
ceiling(town, phase) = clamp(
    BASE[phase] · (population / 10,000) ** 0.38      # population sets ambition
      + institution_boost(town),                     # colleges + camp-hosting schools
    FLOOR[phase], HARD_MAX[phase]
)
BASE      = { phase_a: 50, phase_c: 40 }     # "aggressive" (operator pick)
ALPHA     = 0.38                             # fitted: Boston≈5×, Waltham≈2× a 10k town
FLOOR     = { phase_a: 25, phase_c: 15 }
HARD_MAX  = { phase_a: 400, phase_c: 200 }   # under global max_searches_per_run=1000
```
The `0.38` exponent reproduces the operator's anchors smoothly (10k→1×, Waltham 65k→~2×,
Boston 676k→~5×). Framingham (72k) lands ~2.1× — honest, since it is genuinely
Waltham-sized; a pop curve cannot make it 3× while Waltham is 2×.

`institution_boost = colleges·10 + private_schools·8 + (public_district?·6) + trade·6`
(camp-hosting institutions are discrete provider surfaces, so they raise ambition).

### Adaptive stop (decided: yield-stop can end early; ceiling is the cap)
Run prioritized queries in priority order; track unique NEW provider hosts in a sliding
window (last `W=10` searches). After `FLOOR` searches, **stop early when the window yields
0 new hosts**; otherwise continue to `ceiling`. Productive towns ride up to their big
ceiling; sleepy towns stop near the floor.

### Example ceilings (BASE_A=50)
| Town | Pop | Institutions | Phase A ceiling |
|---|---|---|---|
| Ashby | 3.2k | 0 | 25 (floor) |
| Watertown | 35k | (some private) | ~48–60 |
| Waltham | 65k | 2 colleges + privates | ~102 + boost ≈ **125** |
| Cambridge | 118k | 3 colleges + many schools | ~150+ |
| Boston | 676k | many | ~250 |

> Boston/other cities must be added to `config/town_geo.py` (it is Middlesex-only today).

---

## Thread 2 — College / university discovery (hybrid)

- **Source (hybrid):** curated `config/college_registry.py` (town → colleges: name, .edu
  host) for reliable testing, **plus** dynamic `.edu` discovery (`"colleges universities
  in {town}, MA"` → keep `.edu` hosts) so unknown towns still work.
- **Targeted queries per college** (high-priority slice of the Phase A pool):
  `"{college} pre-college summer program high school"`, `"{college} summer youth camp"`,
  `"{college} sports camp kids"`, `"{college} summer academy ages"`.
- Each college becomes a provider; the engine extracts; the gate filters.

---

## Thread 3 — School discovery (private, public, trade)

Schools host camps too — private/prep schools especially (Fessenden, Shore, St. John's
already leak in via generic search), plus high-school sports camps and vo-tech youth
exploratories. **Smart depth, not literal per-school** (an elementary school almost never
runs its own camp; the district community-ed — already covered by Phase A core — runs
town-wide camps):

| Category | Strategy | Why |
|---|---|---|
| Private / independent / prep | per-institution queries (curated + dynamic `"{town} private school summer camp"`) | highest camp yield among schools |
| Public **high** schools | per-school + `"{town} high school summer camp"` | sports camps, some academic programs |
| Public **middle/elementary** | **district-level only** (`"{town} public schools summer programs"`, already in pool) — NOT per-school | they don't run own camps; per-school = pure waste, killed by yield-stop anyway |
| Trade / vocational / technical | `"{town} vocational technical summer"`, `"{town} trade school summer"` | youth exploratory summer programs |

- **Source (hybrid):** curated `config/school_registry.py` for the pilot town + dynamic
  discovery on school-like domains (`.k12.ma.us`, district/private-school sites).
- These become providers → engine → gate.

### Slop guard (critical — interacts with the new noncamp filter)
The recently-added school-district **service** rule drops ESL / farm-to-school /
transition / enrollment / change-of-address / special-education pages. A real
"`<School> Summer Theater Camp`" does **not** match those, so it survives. Add a
regression test asserting school summer camps pass while service pages drop. Also add a
**higher-ed adult** noncamp category for colleges: drop degree/admissions/grad/
study-abroad/CEU/credit pages; *require* a youth signal (rising-grade / ages / high-
school students), which college youth camps always state.

---

## Output + verification
- One readable file per town: `{TOWN}_INSTITUTION_CAMPS.txt`, sectioned by Colleges /
  Private Schools / Public Schools / Trade. (Plus the rows merge into the normal lists.)
- After coding: run Waltham, **manually open each discovered Bentley/Brandeis/private-
  school page to confirm it is a real youth camp**, write up what was verified, hand the
  txt to the operator to spot-check.

---

## Implementation order (file by file)
1. `config/town_geo.py` — add Boston + missing cities (data).
2. `config/college_registry.py` (new) + `config/school_registry.py` (new) — curated,
   hybrid-backed; Waltham populated first.
3. `config/keywords.py` — prioritized query **pool** (core 53 → activity expansions →
   college templates → school templates) + a builder.
4. `src/search_budget.py` (new) — `town_budget(town)`, `institution_boost(town)`,
   `prioritized_queries(town)`, adaptive `YieldStopper`.
5. `engine/validate/noncamp.py` — higher-ed adult category; keep school-service rule
   narrow.
6. `src/run.py` `_run_discovery_phase` — per-town ceiling, pooled queries, dynamic
   `.edu`/school discovery, yield-based early stop.
7. `src/agentic_gap.py` / `pilot/.../run_pilot.py` — Phase C uses the per-town ceiling.
8. Institution-camps `.txt` writer; wire into the pilot.
9. Tests: budget math, yield-stop, higher-ed slop filter, school-camp-passes regression.
10. Run Waltham; manual page verification; deliver txt.
