# HUB ADAPTER ROADMAP — ZIP-Seeded National Providers

**Scope:** Incorporate three national camp hubs — **Camp Invention** (invent.org), **Skyhawks/Configio** (register.skyhawks.com), and **iD Tech** (idtech.com) — into the Firefly catalog as `parent_ready` registrable sessions, geo-correct to the 54 Middlesex County towns.

**Why these are a new class, not B.5 work:** B.5 starts from a *known provider URL* and walks down. These start from a *town* and inject its ZIP into a templated search. They are **hub seeds**, not crawl seeds. They bypass the recursive navigator entirely; the navigator never needs to discover them. This roadmap slots *alongside* B.5, not inside it.

**Modify, don't rebuild:** Everything below hooks into existing assets — `make_session`, the three-node schema (`info_url` / `details_text` / `register_url`), platform constants in `src/platforms.py`, `config/towns.py`, `session_log`, `relevance.classify_session`, `test_baseline.py`, `eval_history.csv`, `firecrawl_queue.csv`. No new pipeline. No re-import of solved problems.

---

## Sequencing rationale (lowest risk → highest)

| Phase | Provider | Fetch class | New risk introduced |
|-------|----------|-------------|---------------------|
| H0 | (shared) | — | Hub registry + per-town ZIP table + safeguards |
| H1 | Camp Invention | GET-template, status baked into URL | Validates hub_seed end-to-end on the cleanest case |
| H2 | Skyhawks / Configio | GET-template, server-rendered | **Cross-adapter dedup** (routes into WebTrac/MyRec) + season filter |
| H3 | iD Tech | SPA funnel (location → `lid` → reg-flow grid) | Playwright/XHR, multi-hop |
| H4 | (shared) | — | Dedup reconciliation, baseline annotation, cutover |

Build the simplest first so the shared infrastructure (H0) is exercised by an easy provider before the hard ones depend on it.

---

## Phase H0 — Shared hub infrastructure + safeguards (PREREQUISITE)

**Goal:** Stand up the seed registry, the per-town ZIP source-of-truth, the canonical session identity used for dedup, and the gates that must exist *before* any hub emits a row. Per the standing principle: safeguards precede scale.

### H0.1 — Per-town ZIP table (`config/towns.py`)
Add a canonical primary ZIP + city + state to every town. This is the seed input for all three hubs.

```python
TOWNS = {
    "Lexington": {"zip": "02421", "city": "Lexington", "state": "MA"},
    "Burlington": {"zip": "01803", "city": "Burlington", "state": "MA"},
    # ... all 54
}
```

- **Forbidden:** guessing or inferring a ZIP. Each must come from USPS/town .gov. A wrong seed ZIP silently shifts the entire radius.
- **Acceptance:** all 54 towns have a non-empty `zip`; each ZIP passes a 5-digit + MA-prefix (`014xx`–`024xx`) regex.

### H0.2 — Hub registry (`config/hubs.py`, new file)
One declarative entry per hub. No logic here — just the search-URL template and how to fetch it.

```python
HUBS = {
  "camp_invention": {
    "host": "invent.org",
    "adapter": "camp_invention",
    "render": "rendered",         # AJAX result list
    "radius_miles": 25,
    "search_template": (
      "https://www.invent.org/program-search"
      "?field_geolocation_proximity%5Bvalue%5D={radius}"
      "&field_geolocation_proximity%5Bsource_configuration%5D%5Borigin_address%5D={zip}"
      "&field_program_status_value_1%5B%5D=pre-registration"
      "&field_program_status_value_1%5B%5D=registration"
      "&sort_by=field_geolocation_proximity&sort_order=ASC"
    ),
  },
  "skyhawks": {
    "host": "register.skyhawks.com",
    "adapter": "configio",
    "render": "raw",              # server-rendered HTML, no JS wait
    "radius_miles": 10,
    "search_template": "https://register.skyhawks.com/search?zip={zip}&zipdis={radius}",
  },
  "idtech": {
    "host": "idtech.com",
    "adapter": "idtech",
    "render": "playwright",       # SPA, hash route, must wait for grid/XHR
    "radius_miles": None,         # city-name search, not radius
    "search_template": "https://www.idtech.com/location-search?s={city},+{state},+USA&p={page}",
  },
}
```

### H0.3 — Platform constants (`src/platforms.py`)
Add: `CONFIGIO = "configio"`, `CAMP_INVENTION = "camp_invention"`, `IDTECH = "idtech"`, and a class marker `HUB_SEED = "hub_seed"`. Register a detection rule so `register.skyhawks.com` and any `*.configio.com`-backed host map to `CONFIGIO` (the parser is reusable beyond Skyhawks).

### H0.4 — Canonical session identity (dedup key)
The single most important accuracy primitive. Every emitted row gets a stable `session_uid` so the same camp discovered via two paths collapses to one.

Precedence for `session_uid`:
1. If the row resolves to a known platform with a stable id → use it: WebTrac `FMID`, MyRec `ProgramID`, Configio Course # (e.g. `SSA69376`) or `/pd/{id}`.
2. Else → `fuzzy_key = (rapidfuzz token-set normalize(name), venue_zip, start_date)`.

Two rows match if their precedence-1 ids match, **or** their fuzzy_key matches at token-set ratio ≥ 92 *and* same `start_date`. Store `session_uid` on the row.

### H0.5 — Geo from venue, not seed (`src/relevance.py` or a new `geo_resolve`)
Hard rule, applies to all three hubs: the authoritative geo tag is the **venue address parsed from the listing**, never the search ZIP and never the registration domain.
- Carry `geo_town` + `geo_zip` from the venue.
- The geo filter trusts `geo_town`/`geo_zip` over host markers for hub rows (flag rows as `geo_source="venue"`).
- **Why:** verified live — a 02421 (Lexington) + 10mi Skyhawks search returned **zero** Lexington camps; results were in Wayland, Watertown, Carlisle, Concord, Billerica, Burlington. Seed ZIP ≠ camp location.

### H0.6 — Season filter (`relevance.classify_session`)
Hub searches return year-round programs. Drop anything whose parsed `start_date` falls outside the summer window (default **Jun 1 – Aug 31**, configurable in `settings.py`). Verified live: the Skyhawks pull included Sep–Jan year-round sessions.

### H0.7 — Safeguards (these are the pre-scale gates from the existing roadmap, applied here)
1. **register_url verification gate** — every emitted row's `register_url` must 200 and contain a registration affordance (cart/register/program-detail signal). On fail → demote, do not emit as `parent_ready`. Asymmetric: demote only on positive evidence of failure (4xx/5xx or no affordance), not on absence of a check.
2. **Per-host sanity bounds** — but **exempt hub hosts from the explosion ceiling**. One hub search legitimately yields 20+ rows; the single-provider cap would wrongly trip. Give hubs a separate high ceiling (e.g. 500/run/hub) and a zero-floor alarm (a hub returning 0 across all towns = likely template/markup break, not a real empty).
3. **Snapshot diffing** — persist per-hub result snapshots; alarm on run-over-run deltas beyond ±X% so a silent markup change surfaces.
4. **Golden fixtures** — see H1.1/H2.1/H3.1; tests run against saved HTML/JSON, **no network in tests**.

### Phase H0 acceptance (falsifiable)
- [ ] 54/54 towns have validated ZIPs.
- [ ] `config/hubs.py` loads; all three templates render a valid URL when `.format(zip=…, radius=…, city=…, state=…)`.
- [ ] `session_uid` unit-tested: known-id path and fuzzy path each have ≥3 positive and ≥3 negative cases.
- [ ] Hub hosts are exempt from the explosion cap (test asserts a 30-row hub result is *not* truncated).
- [ ] Season filter unit test: a Jan-dated row is dropped, a Jul-dated row is kept.

**Forbidden in H0:** emitting any session; modifying any locked baseline; adding any paid search (these are direct GETs — no Serper credits consumed).

---

## Phase H1 — Camp Invention (cleanest, validates the pattern)

**Goal:** First live hub. GET-templated, `parent_ready` is enforced by the URL itself (`field_program_status_value_1[]=pre-registration|registration`).

### H1.1 — Capture fixture (do this while live)
Fetch `search_template.format(zip="02421", radius=25)` rendered; save the HTML/JSON to `data/_fixtures/camp_invention/02421_25mi.html`. This is the characterization baseline.

### H1.2 — Adapter `adapters/camp_invention.py`
```python
async def fetch(zip: str, city: str, state: str, radius: int,
                existing_register_urls: set[str]) -> list[dict]:
    """Return make_session rows for one town seed."""
```
- Rendered fetch (results are AJAX-injected; raw GET may return an empty shell — confirm against fixture).
- One result card → one `make_session`:
  - `name` = program/school name
  - `register_url` = program detail/register link on invent.org
  - `info_url` = same detail page (or distinct "learn more" if present)
  - `details_text` = grades/ages + dates + price
  - `platform = CAMP_INVENTION`, `kind = "session"`
  - `geo_town`/`geo_zip` parsed from the host school address
- Status is pre-filtered by the URL, so every returned program is presumptively registrable — still run the H0.7 register_url gate (a status can flip).

### H1.3 — Dedup
Camp Invention runs in schools; sites are stable per program id. Dedup on program id across overlapping town radii (25mi from 54 towns is near-total overlap → enumerate once, tag serving towns).

### Phase H1 acceptance
- [ ] Parser reproduces the exact card count of the saved fixture (characterization test, no network).
- [ ] Every emitted row: non-empty `register_url` that passes the gate; `start_date` in summer window; `geo_town` populated from venue (not defaulted to the seed town).
- [ ] 25mi-radius dedup: a program appearing in two town searches emits **once** with both towns tagged.
- [ ] Zero rows with `geo_zip` outside MA.

---

## Phase H2 — Skyhawks / Configio (GET + cross-adapter dedup + season)

**Goal:** Server-rendered GET hub whose **register links route into backends you already adapt** (MyRec `ProgramID`, WebTrac/VermontSystems, ActiveNet/activityreg). This phase's whole risk is dedup correctness, because it can pollute the locked WebTrac=40 / MyRec=89 baselines.

### H2.1 — Capture fixture
Save `register.skyhawks.com/search?zip=02421&zipdis=10` HTML to `data/_fixtures/configio/skyhawks_02421_10mi.html`. (Server-rendered — raw fetch is sufficient, confirmed live.)

### H2.2 — Configio parser `adapters/configio.py`
Per card, extract: title/sport, camp-type subtitle, `/pd/{product_id}/{slug}` detail URL, **register affordance**, price, status text, region, ages **or** grades, date range, times, days, session count, venue address (+ distance), Course #.

Register affordance splits two ways — this drives `register_url`:
- **External Register → external URL present** → `register_url = external_url` (the true registration endpoint; e.g. `carlislema.myrec.com/...ProgramID=30367`, `register1.vermontsystems.com/wbwsc/...module=AR...`, `*.activityreg.com`).
- **Internal cart (`__doPostBack`, "Register"/"Wait List"/"Notify Me")** → `register_url = the /pd/{id}/{slug} page` (the postback isn't a URL; the detail page is the entry point).

Always: `info_url = /pd/{id}/{slug}`. `platform = CONFIGIO`.

### H2.3 — `parent_ready` from status text (not page inference)
- `"Available"` → `parent_ready`.
- `"Full"` (Wait List button) → keep row, mark `registrable = False`; **do not** emit an open register link.
- `"Notify Me"` → hold/drop (not yet open).

### H2.4 — Season filter
Apply H0.6 — the live 02421 pull contained Sep, Oct, Nov, Dec, **Jan 15** year-round sessions. These must be dropped for summer scope.

### H2.5 — Cross-adapter dedup (the critical step)
When `register_url` is an external municipal portal:
1. Resolve its stable id (MyRec `ProgramID`, WebTrac `FMID`/session, ActiveNet activity id).
2. Compute `session_uid` (H0.4) and check against rows already produced by the direct WebTrac/MyRec/ActiveNet adapters.
3. On match → **keep one row**, prefer the external municipal `register_url` as canonical, merge any fields, record `discovered_via = ["skyhawks", "<direct_adapter>"]`.
- **Why it matters:** without this, a Burlington Skyhawks flag-football camp counts twice (once via skyhawks, once via Burlington WebTrac), inflating counts and corrupting the locked baselines.

### Phase H2 acceptance
- [ ] Parser reproduces the **exact** card count of the saved fixture.
- [ ] Every `"Available"` card → `parent_ready`; every `"Full"` → `registrable = False`; counts match a hand-labeled fixture.
- [ ] Every External-Register row: `register_url` host == the external municipal host (asserted), not `register.skyhawks.com`.
- [ ] Season filter removes all non-summer rows (assert 0 rows with month ∉ {6,7,8} on the summer-scoped run).
- [ ] Cross-adapter dedup: a fixture seeded to overlap a known WebTrac/MyRec row collapses to **one** `session_uid`; report removed-duplicate count in the run log.
- [ ] `geo_town`/`geo_zip` taken from the venue line (e.g. Wayland/Watertown/Carlisle), never `02421`.

### Open item to resolve in H2
Pagination: the results footer references page numbers. Confirm whether it's a `p=`/offset param or a `__doPostBack`. The adapter must walk all pages, not just page 1.

---

## Phase H3 — iD Tech (SPA funnel)

**Goal:** Three-hop funnel with a JS-rendered availability grid. Highest effort; build last.

### H3.1 — Capture fixtures (two layers)
1. `location-search?s=Lexington,+MA,+USA&p=1` → save HTML (campus list + `lid`s).
2. A reg-flow page (e.g. Bentley, `lid=32`): in DevTools, capture both the rendered grid **and** the underlying availability XHR (likely a JSON endpoint keyed by `lid`). Save both to `data/_fixtures/idtech/`.

### H3.2 — Adapter `adapters/idtech.py` (three hops)
1. **Location search** → parse nearby campus pages + `lid`. Hit pages `p=1..N` until no new campuses.
2. **Per campus → reg-flow URL:** `…/locations/{state-slug}/{campus-slug}#/reg-flow/avail-charts-lock?lid%5B%5D={lid}&rgnad=true`. The `#/reg-flow/…` is a client-side hash route; the grid loads after settle.
3. **Prefer the XHR over the DOM.** Same playbook as the Sawyer/hisawyer widget XHR adapter: hit the availability JSON keyed by `lid` directly. DOM grid scrape is the fallback only.

Grid → sessions:
- Rows = courses (Coding 101, BattleBots Jr…), columns = week ranges, cells = status.
- **Emit only `Open`-with-price cells.** Skip empty cells and "Try online" — emitting those fabricates sessions for weeks that don't run. The `Open` badge is the `parent_ready` signal.
- Three-node mapping: `register_url` = the campus reg-flow page (**shared across all sessions at that campus** — acceptable); `info_url` = per-course "Course info" link; `details_text` = "Ages 7-9 • Beg-Adv • 1 Week • from $1,129". `platform = IDTECH`.

### H3.3 — Enumerate campuses once
iD Tech has only a handful of MA campuses (Bentley, MIT, Tufts, Wellesley, …). Enumerate campuses once, tag which towns each serves; do not re-run per town.

### Phase H3 acceptance
- [ ] Location-search parser returns ≥ the known MA campuses for a Boston-area seed.
- [ ] Reg-flow parser (against XHR fixture) emits a session for **every** Open+priced cell and **zero** sessions for empty cells (hand-labeled fixture count must match exactly).
- [ ] Each campus's sessions share the correct reg-flow `register_url`; each has a distinct `info_url`.
- [ ] If the XHR path is used, a parallel DOM-fixture test confirms equal session counts (XHR/DOM parity guard).

---

## Phase H4 — Integration, reconciliation, cutover

### H4.1 — Orchestration (`src/run.py` hub mode)
Add a hub pass: for each hub in `HUBS`, for each town seed (deduped by radius overlap), fetch → parse → season-filter → geo-resolve → register_url gate → cross-adapter dedup → emit. Hubs run as their own pass, parallel-safe, independent of the B.5 navigator.

### H4.2 — Global dedup reconciliation
Run the full catalog (B.5 + hub passes) through `session_uid` once more. Produce a reconciliation report: total sessions, per-hub contribution, duplicates collapsed, and the **net delta to each existing per-provider baseline**.

### H4.3 — Baseline policy (annotate, never silently correct)
If hub dedup changes WebTrac/MyRec counts, **annotate** in `test_baseline.py` — e.g. "MyRec 89; +N surfaced via Skyhawks external-register, deduped to existing ProgramIDs, net 0 new." Do not edit the locked floor without an explicit, logged annotation.

### H4.4 — KPI ledger
Append a row to `eval_history.csv` per run: sessions per hub, parent_ready rate, register-gate pass rate, duplicates collapsed, geo-reject count, season-reject count.

### H4.5 — Firecrawl exhaust valve
Any hub host that fails to render/parse after retry → `firecrawl_queue.csv` (e.g. iD Tech if the XHR endpoint changes and DOM scrape also fails).

### Phase H4 acceptance / accuracy scorecard
- [ ] End-to-end run across all 54 towns × 3 hubs completes; reconciliation report generated.
- [ ] **Zero** duplicate `session_uid`s in the final catalog.
- [ ] **Zero** sessions with `start_date` outside the summer window.
- [ ] **Zero** sessions whose `geo_zip` is outside MA / outside the 54-town set's radius.
- [ ] **100%** of `parent_ready` rows pass the register_url verification gate.
- [ ] Existing WebTrac/MyRec baselines unchanged **or** changed only with a logged annotation.
- [ ] Per-hub golden-fixture tests pass with no network access.

---

## Global forbidden actions (all phases)
- No paid searches (these are direct GETs; Serper/DataForSEO credits must not be touched).
- No modifying a locked baseline without an explicit annotation (H4.3).
- No network access inside tests (fixtures only).
- No emitting a `parent_ready` row that hasn't passed the register_url gate.
- No using the seed ZIP or registration domain as the geo tag (venue address only).
- No commit without all phase-gates green.
- No truncating a hub result with the single-provider explosion cap.

## Definition of "most accurate result"
Accuracy here = **every emitted row is (a) registrable now, (b) in the summer window, (c) geo-correct to its real venue, and (d) counted exactly once across all discovery paths.** The four gates that enforce this — register_url verification, season filter, venue-based geo, and `session_uid` dedup — are non-negotiable and are tested per provider against saved fixtures.
