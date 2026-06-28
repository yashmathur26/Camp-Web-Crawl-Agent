# Engine Accuracy Roadmap

**Goal:** a confirmed deliverable where every published row is an individual youth
summer camp, every link points to the real main info page, the registration page
is found (not assumed), and the name actually identifies the camp.

## The core reframe

A URL string is reliable for exactly one thing — **identifying a known
registration platform by host** (`myvscloud.com`, `campscui.active.com`,
`capturepoint.com`, `pinwheel.us`, `hisawyer.com`, CampBrain/Daxko domains, etc).
Those hosts are fixed across sites, so matching them is a fingerprint, not a guess.

For everything else — whether a page on the provider's *own* domain is the signup
page, the info page, or an alumni page — the URL string is noise. The page role
lives in the **page content and its outbound links**, both of which you already
fetch and currently throw away by reducing each page to its path.

So the whole effort is one move: **stop classifying page role from URL strings;
classify it from page content + outbound links, and reserve URL/host matching for
known-platform detection.** The pile of slug regexes (`_NONDETAIL_LEAF_RE`,
`_BAD_REGISTER_RE`, `_REG_INTENT_RE`, `_NONCAMP_SECTION_RE`, `_OFF_TOPIC_RE`)
collapses back to just platform-host detection plus a few hard safety denies.

## Guardrails (carry through every phase)

These come straight from `rules.md` — they keep the new machinery from
re-creating old failures:

- **One gate, one writer (R6).** The deterministic gate decides keep/drop. The
  LLM *verifies and flags*; it never deletes a row. No second verdict system.
- **LLM answerable inputs only, fail open (R3).** A page-role call is made only
  when there is enough rendered text (reuse the ≥400-char guard). Model
  unavailable / timeout / unparseable → keep + route to review, never drop.
- **Evidence, not name strings (R4).** Keep/drop turns on extracted fields and
  page affordances, not on keyword-matching a name.
- **Single LLM call site.** Extend `engine/extract/llm.py`; do not add new
  model-calling sites. You inherit the char guard, JSON-repair + retry, fail-open,
  and per-call logging for free.
- **Don't touch what works.** Vendor adapters (WebTrac, CommunityEd `/class/`,
  MyRec) are accurate today. Every phase must preserve their output.

---

## Phase 0 — Safety net (do before refactoring anything)

**Goal:** be able to detect regressions before you start moving the page-role
decision around.

**Changes**
- Freeze a golden snapshot of the current clean vendor output (WebTrac /
  CommunityEd / MyRec rows) as a characterization test. These must not change.
- Assemble a small labeled fixture set of saved page HTML covering the cases that
  matter: a known-platform catalog page, a flat marketing list of N camps, an
  info-then-register single camp, an external-form register page, and the slop
  classes (blog article, aggregator/directory, about/alumni page, hub/category
  landing). Hand-label each with its true role.
- Wire the existing eval (precision, `info_url_validity`) to run on demand against
  this fixture set, not just the full crawl.

**Done when:** you can run one command that reports precision / info_url validity /
role-classification accuracy on the labeled fixtures, and the vendor golden test
passes.

---

## Phase 1 — Output split + deterministic gate hardening

**Goal:** make "every link accurate, every name real" true *by construction* —
anything that can't clear the bar simply isn't in the confirmed file. This is the
single highest-ROI phase; do it first.

**Changes**
- **Split the deliverable into three tiers**: `confirmed` (the main output),
  `review` (separate file — generic-path / thin-evidence / unresolved rows),
  `gap` (diagnosed, not published — you already have this). The confidence inputs
  get richer in later phases; start with the cheap signals below.
- **Lift the host denylist into the gate.** `_DENY_HOST_RE` currently lives in
  `engine/registry/proposer.py` (behind human review) and never runs at publish
  time. Move it into `gate_program` as a hard pre-check and expand it
  (`*parent*.com`, `parentspaper`, `collegevine`, `*blog.*`, `/tag/`,
  `/category/`).
- **Same-host rule for generic-path rows.** A generic-path row may publish to
  `confirmed` only if its `info_url` host shares the provider's registrable
  domain (or is a known platform tied to that provider). This alone removes the
  CollegeVine blogs, the chch tag-archives, bostonparentspaper, and the
  out-of-state buckscountyparent rows.
- **Reject hub/category/landing pages.** `generic.py` already computes a `hubs`
  set — propagate that flag to the gate so a page the crawler descended *from*
  can't be published as a program. Pair with a slug reject for the obvious hubs
  (`/camps`, `/summer-camps`, `/how-to-enroll`, `/programs`).
- **Extend name-integrity.** Keep the `CHROME_LABELS` frozenset, add a regex for
  multi-word category/article names ("how to enroll", "* programs",
  "class of \d{4}", "\d+ reasons", "ultimate guide", "*.html") and reject
  host-echo names ("ussportscamps.com — Camps").

**Done when:** the `confirmed` file no longer contains any third-party host,
hub/landing page, or chrome-named row; the slop has moved to `review`; vendor
golden test still passes.

---

## Phase 2 — Resolve `register_url` from outbound links (fixes the 95% collapse)

**Goal:** find the actual signup page instead of copying `info_url` into
`register_url` (identical on 908/955 rows today), and get a trustworthy
"did we reach registration" signal.

**Changes**
- For each provider, scan the outbound links of **every fetched page** for a
  known-platform host (`VENDOR_SIGNATURES` / `is_registration_platform_url`).
  The first such link is the real `register_url` — even when it's on a different
  domain (the handoff pattern: `abce.abschools.org → register.capturepoint.com`,
  `communitykangaroo.com → pinwheel.us`). `find_register_link` already does a
  single-page version; run it across all of a provider's fetched pages.
- Populate `register_url` only from a detected enroll affordance or platform link.
  Leave `info_url` as the content page. When they legitimately coincide (WebTrac
  iteminfo), record that, but treat a high identical-rate as a signal the
  resolver isn't running.
- Keep `_BAD_REGISTER_RE` as a safety filter on the *resolved* link (login /
  account / donate / gift-card dead-ends), not as the primary classifier.

**Done when:** `register_url == info_url` rate drops sharply; resolved
`register_url`s point at real platform/enroll endpoints; you can list, per
provider, whether a registration target was found.

---

## Phase 3 — Page-role classification from features (retire the slug regexes)

**Goal:** decide page role from what the page *does*, so it generalizes across
sites instead of needing a new regex per town.

**Changes**
- Compute a small **feature set per fetched page**: `has_enroll_form`,
  `has_cart_cta`, `has_price`, `has_date`, `links_to_known_platform`, `is_hub`,
  `name_in_h1`, `text_len`. Most of these already exist — `EnrollmentSignals` /
  `verify_registrable` detect cart CTAs, price, and platform markers in the HTML;
  promote them from *verdict-upgrade only* to a first-class page classifier.
- Decide role from the features: enroll form / cart / price-near-date →
  **registration**; descriptive prose + program fields, no enroll affordance →
  **info**; neither + about/alumni/news structure → **peripheral**.
- When the feature signals are decisive, that's the answer — no LLM needed.
- Drop the URL slug regexes (`_NONDETAIL_LEAF_RE`, `_REG_INTENT_RE` for *role*)
  back to platform-host detection plus the safety denies only.

**Done when:** role classification accuracy on the Phase 0 fixtures beats the
old slug-regex behavior; the about/alumni/program-description pages that leaked
into the last run are classified `peripheral` and excluded from `confirmed`.

---

## Phase 4 — LLM page verifier on the text-rich residue

**Goal:** resolve the cases the deterministic features can't, using content (not
the URL), with the small local model, as the *last* step.

**Changes**
- Add a page-verifier on top of `engine/extract/llm.py`. Input: rendered page
  text (title/H1 + body chunk), **never the URL path**. Output: three-way JSON
  classification — `registration` / `info` / `peripheral`, temperature 0.
- **Text-length gate is the answerable check.** Reuse the ≥400-char threshold:
  enough text → ask the 1B model; not enough → no call, route to review, flag
  thin.
- **Runs only on the residue.** Fire only when Phase 2/3 signals are silent (no
  platform link, no affordance). Don't pay the model to re-confirm a
  high-confidence deterministic result, and don't give it a chance to overrule
  one. This also keeps per-page LLM cost affordable at your volume.
- **Verifies, never deletes.** Its answer routes confirmed vs review. Fail open
  on any model/parse failure → keep + review. Log every call (purpose, model,
  input, output, parsed).

**Done when:** residue pages get a content-based role; flaky/unavailable model
produces review rows, never dropped rows; LLM call count is a small fraction of
fetched pages.

---

## Phase 5 — Name accuracy

**Goal:** names that identify the camp ("Lexington Recreation — Badminton Camp"),
without breaking dedupe or eval matching.

**Changes**
- **Trust `name_source`.** A name from `<h1>` / `<title>` / JSON-LD is reliable;
  link-text / slug names are weak (that's where "Homeschool.Html" and
  "Programs Activities" come from). Weak-source names don't enter `confirmed`
  without cleanup.
- **Provider-prefixed `display_name`**, separate from the identity name. Broaden
  the prefix policy (drop the `is_generic_name` gate so specific-but-thin names
  like "Badminton Camp" get the provider too), but skip when the provider tokens
  already appear in the name (no "YMCA — YMCA Summer Camp"). Keep `raw_name` for
  audit; the CSV `name` column emits `display_name`, while **dedupe and eval
  match on the bare identity name** so prefixing can't shift recall.
- **LLM normalization on weak names only.** This is perception/formatting
  (allowed), not keep/drop — turn a messy weak-source string into a clean name or
  flag it. Don't run it on clean adapter rows.

**Done when:** confirmed names read as "Provider — Camp", no chrome/host-echo
names remain, and the eval's name-match rate against ground truth is unchanged or
better.

---

## Phase 6 — Coverage rollup + eval floor (make it stick)

**Goal:** turn the standard into something the run enforces, so this can't
regress silently.

**Changes**
- **Provider coverage rollup.** Using Phase 2/3 outputs: for each provider, did
  any fetched page have an enroll affordance or link to a known platform? If yes,
  registration was reached. If no, it's a **missed signup** → review + flagged for
  adapter work. This is the content-grounded version of the "hosts with no
  signup" list and you can trust it.
- **Eval floor in the run.** Make the `confirmed` tier fail the run if precision
  or `info_url_validity` drops below threshold (~95–100%), and surface the
  `register_url == info_url` rate and missed-signup count in the run summary.

**Done when:** a run that would publish slop fails loudly instead of writing it;
the summary shows precision, info_url validity, identical-URL rate, and the
missed-signup provider list.

---

## Sequencing & dependencies

- **0 → 1** first: safety net, then the output split + gate hardening. Phase 1
  alone removes the embarrassing slop and is low-risk.
- **2 and 3** are deterministic and feed each other (the platform-link scan is a
  feature in the role classifier); do them together.
- **4** is built on top of 2/3 so it only sees the residue.
- **5** (names) is largely independent — can run in parallel after Phase 1.
- **6** is the capstone; it consumes outputs from 2/3 and locks in the standard.

## If you only do one thing first

Phase 1's **same-host rule + confirmed/review split.** Together they remove the
out-of-state aggregators and admissions blogs and stop everything else from
masquerading as confirmed — most of the visible accuracy problem, for a few lines
in the gate and the writer.

## Honest tradeoff

This shrinks the published count — national-brand landing pages and most generic
guesses leave the confirmed tier. That's the correct direction: your downstream
Firecrawl stage mines these info_urls, so a bad link doesn't just add a row, it
poisons that analysis. A small accurate list beats a big noisy one here.
