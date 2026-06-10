# IMPLEMENTATION_PLAN.md — B.5 Navigator Refactor

Technical design for replacing the one-hop B.5 picker with a bounded recursive navigator.
Pair with `TASK.md` (units of work), `RULES.md` (constraints), `roadmap.md` (sequencing).

---

## 1. Problem statement

Today `enumerate_provider` (src/platforms.py) fetches the seed page, runs a structured
adapter if `detect_platform` matches, and **only if `len(sessions) < b5_trail_min_sessions`**
falls back to `agent_navigate_provider` (src/camp_navigator.py). That fallback does a single
LLM call (`_pick_agent_urls`) returning ≤3 catalog + ≤2 register URLs, fetches each once, and
stops. Consequences:

- No fan-out: a flat list of N camps yields at most ~3.
- No verification: a register URL is accepted by pattern, never confirmed.
- Schema is binary (catalog/register); the per-camp **info page** has no slot.
- Several rules (`_rank_links_for_agent` cross-host drop, `adapter_llm` "same marketing page"
  reject) discard exactly the info-then-register pages we want.

## 2. Target architecture

A single navigator models each provider site as a graph; every page has a **role**:

```
LANDING   entry page (the seed)
CATALOG   lists multiple camps (fan-out point)
DETAIL    one camp, "the page with all the important information"
REGISTER  cart / checkout / enroll (the verification point)
```

Traversal is a bounded BFS/priority loop in Python. The LLM is called only to (a) classify an
ambiguous page's role and (b) extract camp records from a CATALOG/DETAIL page. Structured
adapters are fast-path shortcuts: on platform detection, the adapter returns many DETAIL/
REGISTER nodes at once, which then pass through the same verification gate as LLM-found nodes.

### Data shape (Phase 1)

Extend `make_session`:

```python
def make_session(name, register_url, *, info_url="", details_text="",
                 platform="", dates="", ages="", price="",
                 source_url="", kind="session") -> dict
```

New CSV column `info_url` after `register_url`. `details_text` optional (short blurb for the
parent-facing catalog).

### Verification (Phase 2)

Pull the deterministic core out of Phase P into:

```python
# src/enrollment_signals.py
def verify_registrable(url: str, html: str) -> EnrollmentSignals
# uses CART_CTA_RE, PRICE_RE, BROCHURE_ONLY_RE, LOGIN_WALL_RE, ADULT_BLOCKER_RE
# returns signals + auto_verdict in {parent_ready, brochure_only, wrong_audience, unverified}
```

The navigator calls this the moment it fetches a REGISTER (or CTA-bearing DETAIL) page and
writes `parent_verdict` onto the session. Phase P stays as an optional batch re-audit.

Register/portal fetches must use `networkidle` (Daxko/CampBrain/Sawyer/WebTrac results render
via JS). Add a `wait` arg to the fetch wrapper.

### The navigator (Phase 3)

New module `src/navigator.py`:

```python
class PageRole(enum.Enum):
    LANDING = "landing"; CATALOG = "catalog"; DETAIL = "detail"; REGISTER = "register"

@dataclass
class NavNode:
    url: str; role: PageRole; depth: int; parent_url: str = ""

async def navigate_provider(seed_url, *, town_hint="", max_depth=3,
                            max_fetches=25) -> list[dict]:
    queue: deque[NavNode] = deque([NavNode(seed_url, PageRole.LANDING, 0)])
    seen: set[str] = set()
    sessions: list[dict] = []
    fetches = 0

    while queue and fetches < max_fetches:
        node = queue.popleft()
        u = normalize_url(node.url)
        if u in seen or node.depth > max_depth:
            continue
        seen.add(u)

        # platform fast-path: many nodes in one shot
        plat = detect_platform(u, ...)
        if plat in _ADAPTERS and node.role in (LANDING, CATALOG):
            for s in await _run_adapter(plat, u, links, text):
                sessions.append(_verify_and_finish(s))   # gate
            continue

        text, links = await _fetch(u, wait=_wait_for(node.role))
        fetches += 1
        role = classify_role(u, text, links) if ambiguous else node.role

        if role == CATALOG:
            for camp_link in extract_camp_links(text, links):   # FAN-OUT
                queue.append(NavNode(camp_link, PageRole.DETAIL, node.depth + 1, u))
        elif role == DETAIL:
            rec = extract_one_camp(u, text, links)              # name/ages/dates
            reg = find_register_link(u, links)                  # toward checkout
            if reg:
                queue.append(NavNode(reg, PageRole.REGISTER, node.depth + 1, u))
            rec["info_url"] = u
            sessions.append(rec)            # completed at REGISTER, or kept w/ CTA
        elif role == REGISTER:
            sig = verify_registrable(u, text)
            _attach_to_parent_detail(sessions, node.parent_url, reg_url=u, signals=sig)

    return _dedupe(sessions)
```

Key decisions:

- **`classify_role` is rules-first.** Use `is_camp_catalog_url`, `crawl_link_score`,
  `is_registration_platform_url`; only call the LLM (role classifier prompt) when rules are
  inconclusive. This is where today's `CAMP_NAVIGATOR_SYSTEM` prompt is repurposed — from
  "pick 3 links" to "what is this page."
- **Fan-out lives in CATALOG handling.** Every camp link becomes its own DETAIL node — this
  is the multi-camp requirement, expressed as a loop, not a top-3 truncation.
- **Adapters fold in.** `_run_adapter` output is wrapped and verified identically; no separate
  return path. Delete the parallel handling in `agent_navigate_provider`.
- **Bounded.** `max_depth`, `max_fetches`, `seen` dedup. Respect the heavy-adapter semaphore.

### Rule loosening (Phase 4)

- `_rank_links_for_agent`: replace the `if host != seed_host and not is_registration_platform_url(u): continue`
  drop with a score penalty so external register targets (Jotform, Google Forms, custom SaaS)
  still reach the model/queue.
- `adapter_llm`: when the only link is the same marketing page, run `verify_registrable` on it;
  if a cart/price/CTA exists, keep it (`info_url == register_url`, verdict from signals) rather
  than rejecting outright.
- LLM call hardening: wrap `chat()` with a JSON-repair pass + one retry; route navigation/
  extraction to `ollama_verify_model`, keep `ollama_fast_model` (1B) for the binary classifier.
- Fix `seen_regs`: separate the catalog-visited set from the register-emitted set.

## 3. Seam to existing code (what you reuse, untouched)

| Reuse as-is | Where |
|---|---|
| Platform detection + structured adapters | `detect_platform`, `_run_adapter`, `_ADAPTERS` |
| Deterministic enroll signals | `enrollment_signals.py` regexes |
| Link scoring / catalog detection | `crawl_link_score`, `is_camp_catalog_url`, `is_registration_platform_url`, `registration_url_priority` |
| Fetch + crawl4ai plumbing | `src/crawl.py`, `_fetch` |
| Quality tiers / deliverables | `session_quality.py`, deliverables writer (read new `info_url`) |
| Logging narration | `session_log.*` |
| Discovery (Phase A/B), geo, denylists | unchanged |

## 4. Config changes

```python
# config/settings.py
"b5_navigator_v2": False,          # flag-gate the new path
"b5_nav_max_depth": 3,
"b5_nav_max_fetches": 25,
# deprecate after P5: b5_agent_nav_max_catalog_fetches, b5_agent_nav_max_register_fetches,
#                     b5_trail_min_sessions
```

## 5. Testing strategy

- **Characterization (P0):** lock current adapter + signals output on fixtures.
- **Navigator unit tests:** feed saved HTML for (a) WebTrac catalog, (b) flat marketing list
  of N camps, (c) info-then-register single camp, (d) external-form register. Assert node
  counts, fan-out, and verdicts.
- **Parity test:** old vs new path on the same seed; new must be a superset on
  `parent_ready` and never lose structured-adapter items.

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Fan-out explodes fetch count on huge catalogs | `max_fetches`, dedup, prioritize by `crawl_link_score` |
| JS portals still return empty | `networkidle` + one retry; mark `needs_trail` not `wrong_audience` |
| Small model mis-classifies role | rules decide most pages; LLM only on ambiguity; repair+retry |
| Adapter regression | P0 characterization tests + baseline diff gate every PR |
| Two paths drift while flag exists | time-box the flag; delete old path in P5 |

## 7. Order of operations

P0 (tests) → P1 (schema) → P2 (inline verify) → P3 (navigator behind flag) →
P4 (loosen rules) → P5 (cut over + delete old path). P0–P2 ship independently; P3 is the
keystone; do not delete old code until the flag runs clean on ≥2 towns.
