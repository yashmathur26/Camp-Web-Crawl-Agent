# Engine Accuracy Roadmap v3 — Remaining Build + Link Resolution (Deep Spec)

Supersedes v2. Same scope (remaining initial Phases 2/3/4/6 + the homepage /
link-bundle work; Part D and the Phase 7 agent still out of scope), but the link
layer is now specified at implementation depth: exact field semantics, resolution
algorithms, the "same link" rules, confidence tiers, edge cases, and full
per-provider traces. Part D redesign and Phase 7 remain out of scope.

---

## 0. Where things stand (implemented — context, do not rebuild)

- **Phase 0 (safety net).** ✅ vendor golden (`tests/test_engine_vendor_golden.py`).
  ◑ fixtures (`engine/eval/fixtures.py`, 8 labeled cases) use **synthetic text, not
  saved HTML** — must become real HTML before Phase 3.
- **Phase 1 (output split + gate hardening).** ✅ tiers (`sessions.csv` /
  `review.csv` / `gaps.csv`); `GateResult.review`; `is_denylisted`
  (`_DENY_HOST_RE` + `_DENY_PATH_RE`); `same_registrable_domain()` (generic rows,
  platform hosts exempt via `is_platform_host`); name hardening
  (`_CATEGORY_NAME_RE`, `_HOST_ECHO_RE`, `_FILENAME_RE`).
- **Phase 5 (names).** ◑/✅ `display_prefixed_name()`, `display_name`/`raw_name`/
  `name_source`; dedupe + eval key on bare `name`. LLM normalization ⤬ deferred to
  Phase 4.

**Recorded deviations (decisions, keep):** `name` = identity / prefix in
`display_name`; `"* programs"` matcher dropped; fixtures synthetic (upgrade before
Phase 3); `hubs` set not yet threaded to gate (fixed in Phase 2a below); no new LLM
call site.

---

## 1. Guardrails (unchanged + one explicit)

- **One gate, one writer.** `gate_program` is the only keep/drop authority; `review`
  is a routing target, not a second verdict system.
- **Single LLM call site** (`engine/extract/llm.py`).
- **Evidence, not name strings; fail open.**
- **Don't touch what works** (vendor golden enforces it).
- **Uncertainty → review, never deletion.** False-negative preference: doubtful rows
  go to `review` (visible, recoverable), never silently dropped or silently
  published. Track recall + review-tier size.

---

## 2. The link model (the core of this document)

Today the run carries two link fields and aliases one into the other (`info_url ==
register_url` on 908/955). The redesign replaces that with **four fields, each with
exactly one job and one consumer**, plus one back-pointer used to resolve them.

### 2.1 Field definitions

| Field | Consumer | Meaning | Nullable | Set by |
|---|---|---|---|---|
| `parent_url` | **human** (deliverable) | the most-specific page we're *confident* about, for a parent to land on | no (always resolves, worst case = homepage) | Phase 6L ladder |
| `info_url` | **Firecrawl** | the content/description page for this specific camp | no | extractor (exists today) |
| `register_url` | **Firecrawl** | the actual signup/enroll endpoint | **yes** (null when none found) | Phase 2 resolver |
| `homepage_url` | fallback + human | provider site root; guaranteed-valid floor | no | Phase 6L (derived) |
| `nearest_hub` | resolver internal | closest catalog/section page above this camp | yes | Phase 2a |

### 2.2 Invariants (assert these in tests)

1. `parent_url` is **never empty** for a confirmed row.
2. `register_url` is **never** produced by copying `info_url`. The only way they may
   be equal is a genuine combined page (a known-platform item page, or an
   on-page enroll form) — and when they are, set a boolean `register_is_info=true`
   so a *real* coincidence is distinguishable from the old aliasing bug. A high
   `register_url == info_url` rate **without** `register_is_info` is a regression
   alarm.
3. `homepage_url` for a **platform-hosted** provider (WebTrac on `*.myvscloud.com`)
   is the provider's **own** site from the registry — never the bare vendor root
   (`myvscloud.com`), which is useless to a parent. If the provider has no own
   domain on record, `homepage_url` = the org's catalog/search root on the platform
   (`majwhaydenweb.myvscloud.com/webtrac/web/search.html`), not `myvscloud.com`.
4. `nearest_hub` is the **nearest** hub ancestor, not the site root
   (`/lexplorations/`, not `lexingtoncommunityed.org`).

### 2.3 "Same link" — what equality means (codifies the earlier question)

Link comparison is **never** raw-string. Three levels, already partly in `urls.py`:

- **Normalize** (`normalize_url`): lowercase host, strip `www.`, drop trailing
  slash, drop tracking params (`utm_*`, `fbclid`, `*session*`, `_csrf`).
- **Platform-canonical** (`canonical_register_url`): on a known platform, identity
  is the platform key — WebTrac collapses to `FMID`+`Module`, MyRec to `ProgramID`;
  everything else dropped. So `…iteminfo.html?FMID=50801580&Module=AR` and
  `…iteminfo.html?Module=AR&FMID=50801580&_csrf=x` are the **same** link.
- **Platform identity** (`register_platform_id`): `host|fmid|50801580` — a stable
  cross-row key for dedupe.

Two links are "the same" iff `normalize_url` equal **or** (on a known platform)
`register_platform_id` equal. **Residual ambiguity** (different paths, similar
content, no platform id) → keep both, flag the near-duplicate for **review**; never
silent-merge (loses a real camp invisibly) and never silent-publish-both (dupes).

---

## 3. Schema (minimal, additive — based on implemented code)

`Session` already has `name`/`display_name`/`raw_name`/`name_source` and the output
has `info_url`/`register_url`. Add three fields only:

```
Session:
  ...
  parent_url:     str         # resolved by the ladder (§6L)
  homepage_url:   str         # provider root (§6L.1)
  nearest_hub:    str = ""    # closest catalog/section page above this camp (§2a)
  register_is_info: bool = False   # true iff register_url legitimately == info_url
  register_confidence: str = ""    # "" | high | medium | low  (§ Phase 2)
```

All five resolved fields live on the `Session` and are persisted, but they do **not
all surface in the same file** — see §4. Dedupe/eval keep keying on bare `name`.

---

## 4. Output surfaces — two files, one set of resolved rows

The same gated rows are emitted as **two views**, so the uncertain link
(`register_url`) never reaches a human. One writer, two outputs — the one-gate /
one-writer rule is intact.

### 4.1 Parent-facing CSV (the deliverable)

**One link per camp: `parent_url`. Nothing else link-wise.** The parent never sees
`info_url` or `register_url`. Columns:

```
display_name, parent_url, dates, ages, price, town, [enriched description fields]
```

This is the uniformity/safety win: every row has exactly one link, it is always
populated (the ladder guarantees it), and it is the link we are *most* confident
about. The field that is allowed to be null or imperfect (`register_url`) is simply
**absent from the file a human reads**, so the deliverable is structurally incapable
of shipping a bad signup link.

### 4.2 Firecrawl manifest (internal handoff — not the deliverable)

Carries the content links for extraction. Messy is fine here — no human reads it; a
null/ugly link costs one less page, not a broken experience. **Keyed by `camp_id`**
so extracted content can be stitched back to the right camp:

```
camp_id, info_url, register_url (nullable), nearest_hub, register_confidence
```

Deduped per provider via `normalize_url` / `canonical_register_url` so a
`nearest_hub` shared by 30 camps is fetched **once** (respects Firecrawl credits).

### 4.3 Merge-back (after Firecrawl runs)

Firecrawl's dissected output is stored under `camp_id`. A merge step joins it back
onto the camp record: the **content** (full description, precise dates, pricing
tiers) extracted from `info_url`/`register_url` can flow into the parent CSV's
**descriptive** columns — but the parent's **link stays `parent_url`**. Content from
the content pages; link from the confident page. The two never cross.

### 4.4 Field → file map

| Field | Parent CSV | Firecrawl manifest |
|---|---|---|
| `parent_url` | ✅ the only link shown | — |
| `display_name` | ✅ | — |
| `info_url` | — | ✅ |
| `register_url` (nullable) | — | ✅ |
| `nearest_hub` | — | ✅ |
| `homepage_url` | on row as ladder fallback; not a column unless wanted | — |
| dates / ages / price | ✅ (enriched by merge-back) | — |

---

## Phase 2a — Preserve hubs to the gate + compute `nearest_hub` (prerequisite)

**Why first:** the register scan (2), the role classifier (3), and the `parent_url`
ladder (6L) all need hub pages and the camp→hub relationship that `generic.py`
currently discards.

**Crawl-tree ancestry (preferred method).** During the bounded follow, record a
parent pointer for every fetched URL: `parent_of[child] = page_it_was_found_on`.
A page is a hub if it's in the existing `hubs` set, or `is_camp_catalog_url(u)`,
or `is_hub_slug(u)`. To compute `nearest_hub` for a camp at URL `X`:

```
def nearest_hub(X):
    cur = parent_of.get(X)
    while cur:
        if is_hub(cur):
            return cur            # FIRST hub ancestor — nearest, not root
        cur = parent_of.get(cur)
    return ""                     # no hub above it
```

**Path-trim fallback** (when ancestry is missing, e.g. JSON-LD-harvested rows): trim
`X`'s path one segment at a time; the first trimmed URL that was fetched **and**
`is_hub` is the nearest hub. `/adventures/excursions-grades-4-5` → try
`/adventures/` → if fetched and hub, use it. Prefer ancestry; fall back to trim.

**Stop dropping hubs.** Keep hub pages in the fetched-page set (they're Phase 2 scan
targets *and* Firecrawl content). They still must **never** publish as a camp row —
thread an `is_hub` flag to the gate so a hub routes to neither `confirmed` nor a
camp row, while its URL survives on child camps as `nearest_hub`.

**Done when:** every generic camp carries a `nearest_hub` (or "" if none); hubs are
retained and never published as camps; vendor golden unaffected.

---

## Phase 2 — Resolve `register_url` (deep)

**Goal:** find the real signup endpoint; populate `register_url` separately and
nullably; emit a confidence tier; never alias `info_url`.

**Inputs per provider:** all fetched pages `{url, html, links[], features}` (features
from Phase 3; until then, host-scan only).

**Resolution order — first hit wins, per camp:**

**Tier HIGH — known-platform outbound link.** Scan outbound links of the camp's own
page first, then its `nearest_hub`, then the provider's other pages. For each link:
`u = normalize_url(link)`; keep if `is_registration_platform_url(u)` or host in
`VENDOR_SIGNATURES`; **reject** if `_BAD_REGISTER_RE` matches (login/account/donate/
gift-card/newsletter). Cross-domain is expected and correct (the handoff). Among
survivors, prefer (1) a link on the camp's own page over the hub, (2) one whose
`register_platform_id` carries an item id (`FMID`/`ProgramID`) over a platform root,
(3) `registration_url_priority()` order if available. → `register_url`,
`register_confidence="high"`.

**Tier MEDIUM — on-page enroll affordance** (needs Phase 3 features). If no platform
link, check the camp's info page for `has_enroll_form` / `has_cart_cta`. If present,
`register_url` = the form's `action` URL if distinct, else the page URL with
`register_is_info=true` (the page genuinely *is* the booking page — correct, not the
bug). → `register_confidence="medium"`.

**Tier LOW — register-intent anchor, confirmed by fetch.** If neither, find links
whose anchor text/path match `_REG_INTENT_RE` (`register|enroll|signup|apply|
jotform|google form|formstack|wufoo|regfox`). Take the top candidate, **fetch it**,
run the affordance check on the *fetched* page. Affordance present → `register_url`
= it, `register_confidence="low"`. Dead end (`_BAD_REGISTER_RE` or no affordance) →
discard. This is the only place URL/anchor strings are trusted, and only as a
*candidate finder* confirmed by content — never as the decision itself.

**Tier NONE.** Nothing found → `register_url = null`, `register_confidence=""`. **Not
a failure.** Verdict caps at `info_confirmed`; coverage rollup (Phase 6) marks "no
signup found → review/adapter."

**Confidence → verdict ceiling:** high → `parent_ready` eligible; medium →
`parent_ready` if other evidence is clean, else `needs_review`; low → `needs_review`;
null → `info_confirmed`. This is the stratified detection that fixes the recall hole
(a real but unrecognized-host signup lands in review, not silently as "none").

**Keep `_BAD_REGISTER_RE`** as a safety filter on the *resolved* link only, not as a
classifier.

**Done when:** `register_url == info_url` rate drops sharply and any remainder
carries `register_is_info=true`; resolved links hit real endpoints; unfound signups
are null; per-provider "registration reached?" is listable; confidence tier present
on every row.

---

## Phase 3 — Feature-based page roles (retire slug regexes for *role*)

**Prereq:** upgrade fixtures to **real saved HTML** (tonight's Firecrawl corpus).

Per-page features: `has_enroll_form`, `has_cart_cta`, `has_price`, `has_date`,
`links_to_known_platform`, `is_hub`, `name_in_h1`, `text_len`. Promote
`EnrollmentSignals` / `verify_registrable` from verdict-upgrade to a first-class
classifier. Role: enroll form / cart / price-near-date → **registration**;
prose + program fields, no affordance → **info**; neither + about/alumni/news →
**peripheral**. Decisive features = answer, no LLM. Retire `_NONDETAIL_LEAF_RE` /
`_REG_INTENT_RE` *for role*; keep URL/host matching only for platform detection +
hard denies. The features here also feed Phase 2's MEDIUM tier and 6L's
parent_url role guard.

**Done when:** role accuracy on real-HTML fixtures beats slug-regex baseline;
about/alumni/description pages → `peripheral`, out of `confirmed`.

---

## Phase 4 — LLM page verifier on the residue

Verifier on `engine/extract/llm.py`. Input: rendered page text (title/H1 + body),
**never the URL**. Output: `registration|info|peripheral` JSON, temp 0. ≥400-char
answerable gate; below → no call, route to review, flag thin. Runs **only on
residue** (Phase 2/3 silent). Verifies, never deletes; fail open → keep + review;
log every call. Fold deferred Phase 5 item here: **LLM name normalization on
weak-source names only** — clean or flag, never on clean adapter rows.

**Done when:** residue gets content-based role; flaky model → review not drops; LLM
calls a small fraction of pages.

---

## Phase 6L — Link bundle + `parent_url` ladder + homepage (deep)

### 6L.1 `homepage_url` derivation

```
def homepage_url(provider, info_url):
    if provider.own_domain:                      # from registry seed/host
        return f"https://{registrable(provider.own_domain)}/"
    host = registrable(host_of(info_url))
    if is_platform_host(host):                    # *.myvscloud.com etc.
        if provider.registry_homepage:
            return provider.registry_homepage     # provider's real site
        return platform_catalog_root(info_url)    # org search/catalog, NOT vendor root
    return f"https://{host}/"
```

`registrable()` = eTLD+1. Never return a bare vendor root for a platform-hosted
provider (invariant §2.2.3).

### 6L.2 `parent_url` ladder (per camp, in order; each rung gated)

```
def parent_url(camp):
    # Rung 1 — the camp's own confident page
    if camp.info_url and role(camp.info_url) in ("info","registration") \
       and not is_hub(camp.info_url) and name_on_page(camp):
        return camp.info_url
    # Rung 2 — nearest hub (the list that CONTAINS this camp)
    if camp.nearest_hub:
        return camp.nearest_hub
    # Rung 3 — homepage (guaranteed floor)
    return camp.homepage_url
```

Rung-1 guards matter: don't hand a parent the info_url if its role is `peripheral`
or it's itself a hub — that's not "this camp's page." The ladder is the entire fix
for the multi-camp problem: a camp with its own page goes straight there; a camp
seen only inside a listing lands on **that listing**, never the bare homepage.

### 6L.3 Firecrawl content set (per provider, deduped)

```
content_set(provider) =
    { c.info_url for c in camps }                 # leaf content pages
  ∪ { c.register_url for c in camps if c.register_url }   # real signups only
  ∪ { c.nearest_hub for c in camps if c.nearest_hub }     # catalog/section pages
  ∪ ({ homepage } if set is otherwise thin)
  deduped via normalize_url / canonical_register_url
```

A hub shared by 30 camps is crawled **once**. Hubs are content-rich for multi-camp
providers — they carry every camp + dates in one place — so they earn their slot in
the extraction manifest as well as being the parent fallback.

### 6L.4 Full per-provider traces (real URLs from the run)

**Single small camp** — `camptinyacorn.org`, one camp, no catalog.
- `info_url` = homepage/about (only content page) · `register_url` = `/register`
  form if `has_enroll_form` else **null** · `nearest_hub` = "" · `homepage_url` =
  `https://camptinyacorn.org/` · **`parent_url` = homepage (rung 3)** — correct, the
  homepage *is* the camp · Firecrawl set = {homepage, register?}.

**Hayden** — WebTrac, `majwhaydenweb.myvscloud.com/webtrac/web/iteminfo.html?FMID=50801580`.
- `info_url` = the iteminfo page · `register_url` = **same page**,
  `register_is_info=true`, `register_confidence="high"` (known platform; the item
  page genuinely books — *not* the aliasing bug) · `nearest_hub` = the WebTrac
  search/catalog root · `homepage_url` = Hayden's own site from registry (**not**
  `myvscloud.com`) · **`parent_url` = the iteminfo page (rung 1)** · Firecrawl set =
  {iteminfo page}. Unchanged in keep/drop; golden test guards it.

**Lexplorations** — own-domain multi-camp, 127 `/class/<slug>` pages.
- e.g. "Food for Thought": `info_url` =
  `…/lexplorations/class/food-for-thought-june-29-july-2/` · `register_url` = cart
  affordance on the class page (MEDIUM) or a platform link if present, else null ·
  `nearest_hub` = `https://lexingtoncommunityed.org/lexplorations/` · `homepage_url`
  = `https://lexingtoncommunityed.org/` · **`parent_url` = the class page (rung 1)**;
  if a class were seen only in the listing → **`/lexplorations/` (rung 2)**, never the
  community-ed homepage · Firecrawl set = {each class page} ∪ {`/lexplorations/`}.

**YMCA** — big, nested hubs, off-host signup, `ymcaboston.org`.
- Gate triage first: `/healthy-living/youth-sports` → role `peripheral` → review,
  not a camp; `ymcaboston.org — Day Camps` (host-echo, hub) → kept as hub, not a row.
- Real camp "Cabot Day Camp" (`/camps/day-camps/waltham-camp-guide`): `info_url` =
  the guide page (camp lives inside it) · `register_url` = off-host Daxko/ActiveNet
  link via the outbound scan (HIGH, cross-domain), else null · `nearest_hub` =
  `/youth-and-family/camps/day-camps` (**nearest**, not `ymcaboston.org`) ·
  `homepage_url` = `https://ymcaboston.org/` · **`parent_url`** = the camp's own page
  if one exists (rung 1), else the day-camps guide/hub (**rung 2**) — never the bare
  YMCA homepage while a camp listing exists · Firecrawl set = {guide page, day-camps
  hub} ∪ {Daxko page if found}.

**Running Brook** — generic, unknown platform, `runningbrook.org`, camps under
sections (`/adventures/`, `/day-camp/`).
- Gate triage: `/day-camp/schedules` → logistics → review; `runningbrook.org — Day
  Camp` (host-echo, `/day-camp/day-camp` section root) → hub, not a row.
- "Excursions" (`/adventures/excursions-grades-4-5`): `info_url` = that page ·
  `register_url` = on-page form (MEDIUM) if present, else **null +
  `info_confirmed`** (no recognized platform — honest degradation, the parent is
  unaffected) · `nearest_hub` = `https://runningbrook.org/adventures/` (**nearest**,
  not site root) · `homepage_url` = `https://runningbrook.org/` · **`parent_url` =
  the Excursions page (rung 1)**; a camp seen only in the section listing → the
  `/adventures/` page (**rung 2**) · Firecrawl set = {detail pages} ∪
  {`/adventures/`, `/day-camp/`}.

**Done when:** every confirmed camp has a non-empty `parent_url` at the most
specific rung it earned; no camp lands on a bare homepage when a nearer hub exists;
`register_url` is null (never a duplicate) when unfound; the **parent CSV shows only
`parent_url`** (no `info_url`/`register_url`); the **Firecrawl manifest** is a
deduped per-provider content set keyed by `camp_id` (§4); and a merge-back step
joins Firecrawl's extracted content onto the camp record without changing
`parent_url`.

---

## Phase 6 — Coverage rollup + eval floor (capstone)

- **Coverage rollup:** per provider, registration reached? (any HIGH/MEDIUM
  `register_url`, or any page with an enroll affordance/platform link). No →
  **missed signup → review + adapter flag.**
- **Eval floor in the run** — fail the run if `confirmed` precision or
  `info_url_validity` drops below ~95–100%. Surface in the summary: precision,
  info_url validity, **`register_url == info_url` rate split by `register_is_info`**
  (real-coincidence vs regression), **`register_confidence` distribution**,
  **`parent_url` rung distribution** (how often rung 1 vs 2 vs 3), missed-signup
  list, and **review-tier size** (the false-negative gauge).

**Done when:** a slop run fails loudly; the summary shows the link metrics above on
one screen.

---

## Link-layer edge cases (assert as tests)

| Case | Expected behavior |
|---|---|
| Platform item page is both info & booking (WebTrac) | `register_url == info_url`, `register_is_info=true`, confidence high — *not* a regression |
| Off-host signup (Daxko/CampBrain/pinwheel) | resolved cross-domain via scan; `parent_url` stays on provider page |
| Real signup on unrecognized host (Jotform/custom) | LOW tier via intent+fetch+affordance → review, not "none" |
| No online registration at all | `register_url=null`, `info_confirmed`, `parent_url` = camp page or hub |
| Camp only listed in a hub, no own page | `parent_url` = nearest hub (rung 2) |
| Nested hubs (`/programs/summer/<camp>`) | `nearest_hub` = closest (`/programs/summer/`), not `/programs/` or root |
| Locale mirror (`/es/...`) of same camp | dedupe via normalize_url; one row, not two |
| Two paths, same content, no platform id | keep both, flag near-dup → review |
| Platform-hosted provider homepage | provider's own site or platform catalog root, never bare `myvscloud.com` |

---

## Sequencing & dependencies

- **2a first** — unblocks 2, 3, 6L (hubs + `nearest_hub`).
- **Upgrade fixtures to real HTML before 3** (tonight's Firecrawl corpus).
- **2 + 3 together** — the platform-link scan is also a Phase 3 feature; 2's MEDIUM
  tier needs 3's affordance signals.
- **4** rides on 2/3 (residue only).
- **6L** needs 2a (`nearest_hub`) + 2 (`register_url` + confidence) + 3 (role guard).
- **6** is the capstone; it measures the link metrics above.

## If you only do one thing next

**Phase 2a + Phase 2.** Preserving hubs and resolving a real, confidence-tiered
`register_url` kills the 95% collapse and unblocks the `parent_url` ladder — the two
changes the whole link bundle stands on.

## Honest tradeoff (carried over)

This shrinks `confirmed`. Correct: Firecrawl mines these links, so a bad link
propagates noise. With the bundle, "we couldn't find the signup" degrades to a safe
`parent_url` + null `register_url` instead of a broken row — the failure mode moves
off the parent and onto an optional Firecrawl input.
