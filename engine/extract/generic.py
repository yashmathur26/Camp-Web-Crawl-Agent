"""Generic long-tail extractor (task 5.2, plan §7) — vendor: unknown.

Pipeline: rendered seed -> deterministic harvest (JSON-LD, heading+evidence
clusters) -> bounded same-host follow (depth<=2, scored, media refused,
budgeted) -> LLM extraction (R3, fail open) -> candidates to the gate.
Thin/blocked/empty -> diagnosed gap, ZERO LLM calls.
"""

from __future__ import annotations

import json
import re
from collections import deque
from urllib.parse import urlparse

from config_engine import ENGINE
from engine.extract.base import ExtractResult, Extractor, group_sessions_into_programs
from engine.fetch.client import Budget, BudgetExceeded, FetchClient
from engine.fetch.urls import is_media_url, normalize_url
from engine.model import Gap, Program, Provider, Session
from engine.validate.gate import is_hub_slug

_JSONLD_RE = re.compile(r'<script[^>]+ld\+json[^>]*>([\s\S]*?)</script>', re.I)
_EVENT_TYPES = {"event", "childrensevent", "course", "educationevent", "camp"}
# Ported crawl_link_score essence: follow-worthy paths on a camp site. Includes
# common camp-SECTION words (adventure/leadership/creative/...) so keyword-less
# section pages like /adventures or /creative-arts get followed — their sub-camp
# detail pages live one level deeper (Running Brook finding).
_FOLLOW_RE = re.compile(
    r"camp|summer|program|clinic|register|enroll|class|"
    r"adventure|explor|trek|voyage|leadership|specialty|junior|teen|youth|"
    r"kids?|creative|\barts?\b|\bsports?\b|academy|workshop|intensive|session",
    re.I,
)
_SKIP_RE = re.compile(r"about|contact|faq|donate|news|blog|gallery|privacy|login|account", re.I)
# Sections that never lead to youth summer camps (ported junk-path knowledge +
# the YMCA/JCC/LifeTime feedback round): fitness floors, weight loss, adult
# wellness, after-school/childcare, membership. Absolute skips for follow AND
# record scoping — even when the path also says "program" or "class".
_NONCAMP_SECTION_RE = re.compile(
    r"fitness|health-?wellness|weight-?loss|weightloss|wellness|after-?school|"
    r"enrichment|child-?care|child-?watch|membership|personal-?train|massage|"
    r"aquatics|group-?exercise|find-a?-?program|adult|education-care|"
    r"research|innovation|"
    # Recruitment/staffing sections — never camps; following them wastes the
    # page budget (Running Brook /join-our-team/*-counselors finding).
    r"join-our-team|careers?|/jobs?|employment|hiring|work-(?:for|with)-us",
    re.I,
)
_CAMP_PATH_RE = re.compile(r"camp|summer", re.I)
# Catalog/search roots that are hubs regardless of the crawl tree (platform search
# pages, rec-dept activity listings). Used by Phase 2a's is_hub.
# Catalog/search ROOTS only (a hub) — NOT platform item pages (iteminfo.html under
# /webtrac/ is the camp's own page, not a catalog). Match the search endpoint, not
# every webtrac URL.
_CATALOG_URL_RE = re.compile(
    r"search\.html|activities/default\.aspx|/catalog\b|/program-search",
    re.I,
)


def is_camp_catalog_url(url: str) -> bool:
    return bool(_CATALOG_URL_RE.search(url or ""))


# Weak name provenance (Phase 4/5): slug/link/llm names are the ones worth running
# the LLM normalizer over; jsonld/title are already clean.
_WEAK_SOURCES = {"slug", "link_text", "link", "llm"}


def _looks_messy(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    return bool(
        "." in n                              # "Homeschool.Html"
        or re.search(r"\d", n)                # ids/slugs with digits
        or ("_" in n)                          # raw_slug_form
        or (" " not in n and len(n) < 6)      # cramped single token
    )
# Locale mirrors (/es/, /pt-br/, ...) are the same camp in another language —
# following them produces duplicate rows (ymcaboston Spanish-mirror finding).
_LOCALE_PREFIX_RE = re.compile(
    r"^/(?:es|fr|pt|de|zh|ru|ar|it|ja|ko|vi|ht|pl|hi)(?:-[a-z]{2})?/", re.I
)
# Register-link discovery. Intent uses \b so "/enroll" matches a real enroll
# page but NOT "/enrollment/...change-of-address" (a school service page).
_REG_INTENT_RE = re.compile(
    r"/(?:register|enroll|signup|reg-flow)\b|/sign-up\b|register\.php", re.I
)
# Targets that look like registration but are account/portal/marketing dead-ends
# (Waltham wrong-register-link findings): never point a camp at these.
_BAD_REGISTER_RE = re.compile(
    r"login|sign-?in|/account|my-?account|member-?portal|memberportal|/user/|"
    r"change-of-address|welcome-services|belt-test|gift-?card|mailing-list|"
    r"newsletter|donate|password|logout|destination=",
    re.I,
)
_DATES_RE = re.compile(
    r"(?:june|july|august)\s*\d{1,2}(?:[a-z]{2})?(?:\s*[-–]\s*(?:[a-z]+\s*)?\d{1,2}(?:[a-z]{2})?)?"
    r"|\b[678]/\d{1,2}\s*[-–]\s*[678]?/?\d{1,2}\b", re.I)
_AGES_RE = re.compile(r"ages?\s*:?\s*\d{1,2}\s*(?:[-–to&]+\s*\d{1,2})?|grades?\s*:?\s*(?:pre)?[k0-9][-–k0-9 ]{0,8}|preschool|pre-k", re.I)

# Catalog/multi-page extraction (Running Brook / Middlesex finding): a site with
# one page per camp must be fully enumerated, not just its first 4 pages.
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
# Leaf slugs that are NOT a camp (info/admin pages that still pass the follow
# filter). A detail page with one of these as its last path segment is skipped.
_NONDETAIL_LEAF_RE = re.compile(
    r"^(?:faqs?|register|registration|how-to-register|tuition|rates|dates-rates|"
    r"forms?|financial-aid|bus-program|extended-day|extended-day-program|"
    r"counselors?|join-our-team|contact|about|resources?|family-resources|"
    r"campanion|directions|map|staff|employment|policy|policies|home|index|"
    # Leadership / staff-pipeline tracks are not camps (operator: Running Brook
    # Leadership Training / Young Leaders excluded).
    r"leadership[a-z-]*|young-leaders?|leaders?-in-training|counselor-in-training)$",
    re.I,
)
# Age/grade band embedded in a detail-page slug, e.g. "trekkers-grades-5-6" or
# "excursions-ages-4-12" — reliable evidence even when the page body doesn't
# state it in a form the date/age regexes catch (Running Brook finding).
_SLUG_AGE_RE = re.compile(r"\b(grades?|ages?)-((?:pre)?k?\d{1,2})(?:-(\d{1,2}))?\b", re.I)


def slug_age(url: str) -> str:
    leaf = urlparse(url).path.rstrip("/").split("/")[-1]
    m = _SLUG_AGE_RE.search(leaf)
    if not m:
        return ""
    kind = "Grades" if m.group(1).lower().startswith("grade") else "Ages"
    rng = m.group(2) + (f"-{m.group(3)}" if m.group(3) else "")
    return f"{kind} {rng}"


def slug_name(url: str) -> str:
    """Camp name from a detail-page slug (the reliable per-camp identifier):
    "creative-arts-camp" -> "Creative Arts Camp", "trekkers-grades-5-6" ->
    "Trekkers". Empty/poor (numeric/id) slugs return "" so the caller falls back
    to the page heading."""
    leaf = urlparse(url).path.rstrip("/").split("/")[-1]
    leaf = _SLUG_AGE_RE.sub("", leaf).strip("-_ ")
    name = re.sub(r"[-_]+", " ", leaf).strip()
    # Reject id-like slugs (mostly digits / too short) — heading is better there.
    if len(name) < 3 or not re.search(r"[a-z]{3}", name, re.I) or sum(c.isdigit() for c in name) > len(name) / 2:
        return ""
    return name.title()


def page_title(html: str, url: str) -> str:
    """Best human name for a detail page: <h1>, then <title> (site-name suffix
    stripped), then a title-cased URL slug."""
    for rx in (_H1_RE, _TITLE_TAG_RE):
        m = rx.search(html or "")
        if m:
            t = re.sub(r"<[^>]+>", " ", m.group(1))
            t = re.sub(r"\s+", " ", t).strip()
            t = re.split(r"\s+[|–—]\s+|\s+-\s+", t)[0].strip()
            # Drop a trailing "(Grades 5-6)" / "(Ages 7-12)" qualifier — that's age
            # metadata, not the camp's name.
            t = re.sub(r"\s*\((?:grades?|ages?)[^)]*\)\s*$", "", t, flags=re.I).strip()
            if len(t) >= 3:
                return t
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").strip().title()


def _detail_record(url: str, text: str, html: str) -> dict | None:
    """Synthesize one program record from a camp DETAIL page (no JSON-LD/LLM
    needed): name from the page heading, evidence from the page text. Returns
    None for non-detail (info/admin) pages."""
    leaf = urlparse(url).path.rstrip("/").split("/")[-1].lower()
    if not leaf or _NONDETAIL_LEAF_RE.match(leaf):
        return None
    sa = slug_age(url)
    has_date = bool(_DATES_RE.search(text))
    has_age = bool(_AGES_RE.search(text)) or bool(sa)
    if not (has_date or has_age or "camp" in leaf):
        return None
    # Slug is the reliable per-camp name; the page <h1> is often a site banner
    # ("Running Brook Camps") repeated across pages, which collides on dedup.
    slug = slug_name(url)
    name = slug or page_title(html, url)
    # name_source feeds the gate's Phase-5 trust check: a slug is weak, a page
    # heading/<title> is reliable.
    name_source = "slug" if slug else "title"
    return {"name": name, "info_url": url,
            "dates": "", "ages": sa, "price": "", "_detail": True,
            "name_source": name_source}


def _section_children(parent_url: str, links: list[dict]) -> list[str]:
    """Same-host links whose path is strictly UNDER the parent's path (a section's
    detail pages, e.g. /adventures -> /adventures/trekkers). Relaxed filter
    (skip/non-camp/media only) so keyword-less sub-camp slugs are still followed."""
    host = urlparse(parent_url).netloc.lower().replace("www.", "")
    base = urlparse(parent_url).path.rstrip("/")
    if not base:
        return []
    out: list[str] = []
    for l in links:
        u = normalize_url(l.get("url", ""))
        if not u or is_media_url(u):
            continue
        if urlparse(u).netloc.lower().replace("www.", "") != host:
            continue
        path = urlparse(u).path
        if not path.lower().startswith(base.lower() + "/"):
            continue
        if _NONCAMP_SECTION_RE.search(path) or _SKIP_RE.search(path):
            continue
        out.append(u)
    return out[: int(ENGINE["generic_max_follows"])]


def jsonld_events(html: str) -> list[dict]:
    out = []
    for m in _JSONLD_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            for n in ([node] + (node.get("@graph") or []) if isinstance(node.get("@graph"), list) else [node]):
                t = n.get("@type")
                types = {str(x).lower() for x in (t if isinstance(t, list) else [t])}
                name = str(n.get("name") or "").strip()
                if types & _EVENT_TYPES and name:
                    out.append({"name": name,
                                "dates": str(n.get("startDate") or "").split("T")[0],
                                "ages": "", "price": "", "name_source": "jsonld"})
    return out


def score_follow_links(seed_url: str, links: list[dict]) -> list[str]:
    host = urlparse(seed_url).netloc.lower().replace("www.", "")
    seen, scored = set(), []
    for l in links:
        u = normalize_url(l.get("url", ""))
        if not u or u in seen or u == normalize_url(seed_url) or is_media_url(u):
            continue
        if urlparse(u).netloc.lower().replace("www.", "") != host:
            continue
        path = urlparse(u).path
        # Score path+text only — the domain itself often contains "camp".
        blob = f"{path} {l.get('text', '')}"
        if _LOCALE_PREFIX_RE.match(path):
            continue  # non-English mirror of a page we already follow in English
        if _NONCAMP_SECTION_RE.search(path):
            continue  # fitness/afterschool/etc. — never camps (absolute)
        if _SKIP_RE.search(blob) and not _FOLLOW_RE.search(blob):
            continue
        if not _FOLLOW_RE.search(blob):
            continue
        seen.add(u)
        scored.append(u)
    return scored[: int(ENGINE["generic_max_follows"])]


def scope_to_camp_pages(records: list[dict]) -> list[dict]:
    """Camp-page priority (YMCA/JCC feedback): multi-program orgs list camps on
    /camp(s)|/summer* pages and everything else (fitness, enrichment,
    after-school) elsewhere. If any record came from a camp-path page, keep
    ONLY those; always drop records from known non-camp sections."""
    def path_of(r):
        return urlparse(r.get("info_url", "")).path

    records = [r for r in records if not _NONCAMP_SECTION_RE.search(path_of(r))]
    campy = [r for r in records if _CAMP_PATH_RE.search(path_of(r))]
    if not campy:
        return records
    # Keep non-camp-path rows with STRONG own evidence (dates AND ages), OR that
    # are synthesized per-page detail records (a dedicated camp detail page IS the
    # evidence — Running Brook /adventures/trekkers finding). Camp Middlesex's
    # real camps live at /about-us/program (round-3 finding).
    strong = [r for r in records if r not in campy
              and (r.get("_detail")
                   or ((r.get("dates") or "").strip() and (r.get("ages") or "").strip()))]
    return campy + strong


def demote_activity_menus(records: list[dict]) -> list[dict]:
    """Drop activity-AREA menus mistaken for programs (Camp Middlesex finding):
    a large batch of records from ONE page whose names are 1-2 generic tokens
    with uniform/copied evidence is the camp's activity list (Archery, Gaga,
    Soccer...), not its programs — the real camps are the dated, multi-word
    records from the provider's program pages. Structural rule, not keywords."""
    from collections import Counter, defaultdict

    by_page = defaultdict(list)
    for r in records:
        by_page[r.get("info_url", "")].append(r)

    keep: list[dict] = []
    for page, rows in by_page.items():
        # Brand/nav menus (US Sports finding): >=3 same-page records whose
        # extracted (dates, ages) are IDENTICAL are nav cards, not programs —
        # real weekly camps (Viking) carry distinct date windows.
        if len(rows) >= 3:
            combos = Counter(((r.get("dates") or "").strip(), (r.get("ages") or "").strip())
                             for r in rows)
            top, n = combos.most_common(1)[0]
            if n / len(rows) >= 0.8 and len(rows) >= 3 and top != ("", "") and n >= 3:
                if all(len(r["name"].split()) <= 6 for r in rows):
                    continue  # drop the whole nav-card batch
        short = [r for r in rows if len(r["name"].split()) <= 2]
        if len(rows) >= 8 and len(short) / len(rows) >= 0.7:
            ages = Counter((r.get("ages") or "").strip() for r in rows)
            uniform = ages.most_common(1)[0][1] / len(rows) >= 0.7
            dated = [r for r in rows if (r.get("dates") or "").strip()]
            if uniform and len(dated) <= 2:
                # activity menu: keep only rows with real distinct evidence
                keep.extend(r for r in rows
                            if (r.get("dates") or "").strip()
                            or len(r["name"].split()) >= 3)
                continue
        keep.extend(rows)
    return keep


class GenericExtractor(Extractor):
    vendor = "unknown"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        from engine.fetch.render import fetch_rendered

        budget = Budget()
        text, links, html = fetch.fetch_text(provider.seed_url, budget=budget)
        if len(text.strip()) < 400:
            budget.check()
            text, links, html = await fetch_rendered(
                provider.seed_url, cache=fetch.cache, log=fetch.log
            )
        if len(text.strip()) < 400:
            reason = "blocked" if "403" in (fetch.log[-1].note if fetch.log else "") else "empty"
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason=reason,
                        evidence=f"seed yielded {len(text.strip())} chars after render",
                        suggested_action="manual review"),
                fetch_log=fetch.log,
            )

        # Deterministic harvest first (R5.7): JSON-LD events.
        records: list[dict] = [{**e, "info_url": provider.seed_url} for e in jsonld_events(html)]

        # Bounded follow: depth 1 (seed children) + depth 2 (a section's own
        # detail pages). Total pages capped; each fetched page keeps its html so
        # a detail page can be turned into a program even without JSON-LD/LLM.
        max_pages = int(ENGINE["generic_max_follows"]) * 3
        pages: list[tuple[str, str, str]] = [(provider.seed_url, text, html)]
        visited: set[str] = {normalize_url(provider.seed_url)}
        # Phase 2a crawl-tree ancestry: normalized(child url) -> the page it was
        # found on. Seed children point at the seed; section children at the section.
        parent_of: dict[str, str] = {}
        # Phase 2 register scan needs every fetched page's outbound links + html.
        page_links: dict[str, list[dict]] = {normalize_url(provider.seed_url): links}
        page_html: dict[str, str] = {normalize_url(provider.seed_url): html}
        seed_children = score_follow_links(provider.seed_url, links)
        for cu in seed_children:
            parent_of.setdefault(normalize_url(cu), provider.seed_url)
        queue: deque[tuple[str, int]] = deque((u, 1) for u in seed_children)
        hubs: set[str] = set()  # section pages we descended FROM (not camps themselves)
        while queue and len(pages) < max_pages:
            u, depth = queue.popleft()
            nu = normalize_url(u)
            if nu in visited:
                continue
            visited.add(nu)
            try:
                budget.check()
            except BudgetExceeded:
                break
            ptext, pl, phtml = fetch.fetch_text(u, budget=budget)
            if len(ptext.strip()) < 400:
                continue
            pages.append((u, ptext, phtml))
            page_links[nu] = pl
            page_html[nu] = phtml
            records.extend({**e, "info_url": u} for e in jsonld_events(phtml))
            if depth < 2:  # one more level: this section's detail pages
                children = [
                    cu for cu in _section_children(u, pl) if normalize_url(cu) not in visited
                ]
                if children:
                    hubs.add(nu)  # this page is a section overview, not a camp
                    for cu in children:
                        parent_of.setdefault(normalize_url(cu), u)
                    queue.extend((cu, depth + 1) for cu in children)

        # Phase 2a — nearest_hub resolver. A camp's nearest hub is the FIRST hub
        # ancestor up the crawl tree (not the site root); when ancestry is missing
        # (JSON-LD-harvested rows) fall back to trimming the path one segment at a
        # time to the first fetched hub. Hubs are retained as fetched pages (Phase 2
        # scan + Firecrawl content) but never publish as camp rows.
        fetched_norm = {normalize_url(pu) for pu, _, _ in pages}

        def _is_hub(candidate: str) -> bool:
            return (normalize_url(candidate) in hubs
                    or is_hub_slug(candidate) or is_camp_catalog_url(candidate))

        def _nearest_hub(camp_url: str) -> str:
            seen: set[str] = set()
            cur = parent_of.get(normalize_url(camp_url), "")
            while cur and cur not in seen:
                seen.add(cur)
                if _is_hub(cur):
                    return cur
                cur = parent_of.get(normalize_url(cur), "")
            # Path-trim fallback over fetched pages.
            p = urlparse(camp_url)
            segs = p.path.rstrip("/").split("/")
            while len(segs) > 1:
                segs = segs[:-1]
                trimmed = f"{p.scheme}://{p.netloc}{'/'.join(segs)}/"
                if normalize_url(trimmed) in fetched_norm and _is_hub(trimmed):
                    return trimmed
            return ""

        # Per-page deterministic detail records (catalog/multi-page sites): every
        # followed camp-detail page (a non-hub leaf) becomes its own program with
        # its OWN url — so a site with one page per camp is fully + accurately
        # enumerated. Section/hub pages are excluded (they're overviews, not camps).
        had_jsonld = bool(records)
        have = {normalize_url(r["info_url"]) for r in records}
        added_detail = 0
        for u, ptext, phtml in pages[1:]:  # skip the seed page itself
            nu = normalize_url(u)
            if nu in have or nu in hubs:
                continue
            rec = _detail_record(u, ptext, phtml)
            if rec:
                records.append(rec)
                have.add(nu)
                added_detail += 1

        # LLM extraction — runs when JSON-LD found nothing, to capture camps a
        # site LISTS in prose on one page. SUPPLEMENTS detail records (union;
        # detail records were added first so they win name-dedup with correct
        # per-camp urls). Skips hub/section pages so it can't relabel an overview
        # as a camp. R3; fail OPEN on None.
        if not had_jsonld:
            from engine.extract.llm import extract_programs

            for u, ptext, _ in pages[:4]:
                if normalize_url(u) in hubs:
                    continue  # don't let the LLM relabel a section overview as a camp
                got = extract_programs(ptext, u, provider.town)
                if got is None:
                    continue  # model failure — deterministic results stand
                records.extend({**r, "info_url": u, "name_source": "llm"} for r in got)

        # Drop overview records harvested FROM a section/hub page (JSON-LD or LLM
        # that named the section itself, e.g. "Running Brook Camps" on /day-camp);
        # the section's individual camps are captured as their own detail records.
        records = [r for r in records if normalize_url(r["info_url"]) not in hubs]

        # Deterministic enrichment: pull dates/ages evidence from page text.
        for r in records:
            page_text = next((t for u, t, _ in pages if u == r["info_url"]), "")
            if not r.get("dates"):
                m = _DATES_RE.search(page_text)
                r["dates"] = m.group(0) if m else ""
            if not r.get("ages"):
                m = _AGES_RE.search(page_text)
                r["ages"] = m.group(0) if m else ""

        if not records:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="needs_review",
                        evidence=f"rendered {len(text)} chars but no program records harvested",
                        suggested_action="check page structure; consider a vendor adapter"),
                fetch_log=fetch.log,
            )

        records = scope_to_camp_pages(records)
        records = demote_activity_menus(records)

        # Phase 2 register resolution (per camp, confidence-tiered, never aliased).
        from engine.extract.register import resolve_register

        def _budgeted_fetch(u: str):
            budget.check()
            return fetch.fetch_text(u, budget=budget)

        def _resolve(camp_url: str, nh: str):
            cu = normalize_url(camp_url)
            others = [(pu, ln) for pu, ln in page_links.items()
                      if pu != cu and pu != normalize_url(nh)]
            try:
                return resolve_register(
                    camp_url,
                    own_links=page_links.get(cu, []),
                    own_html=page_html.get(cu, ""),
                    nearest_hub=nh,
                    hub_links=page_links.get(normalize_url(nh), []) if nh else [],
                    other_page_links=others,
                    context="",
                    fetch=_budgeted_fetch,
                )
            except BudgetExceeded:
                from engine.extract.register import RegisterResolution
                return RegisterResolution()

        from engine.extract.features import role_of_page

        seen: set[str] = set()
        sessions = []
        for r in records:
            key = r["name"].lower().strip()
            if key in seen:
                continue
            seen.add(key)
            nh = _nearest_hub(r["info_url"])
            rr = _resolve(r["info_url"], nh)
            cu = normalize_url(r["info_url"])
            page_text = next((t for u, t, _ in pages if normalize_url(u) == cu), "")
            role, _feat = role_of_page(
                r["info_url"], page_html.get(cu, ""), page_text,
                name=r["name"], links=page_links.get(cu, []),
                is_hub=cu in hubs,
            )
            name, name_source = r["name"], r.get("name_source", "")
            # Phase 4 (residue only): when Phase 2/3 are silent — deterministic role
            # is peripheral AND no platform/register link found — ask the 1B model
            # for a content-based role. Fail open: None keeps peripheral (→ review).
            if role == "peripheral" and not rr.confidence:
                from engine.extract.llm import verify_page_role

                llm_role = verify_page_role(page_text, h1=name)
                if llm_role:
                    role = llm_role
            # Phase 4 (folded Phase 5): normalize a weak-source name only when it
            # looks messy; clean → use it, "" → leave for the gate's weak-name
            # review, None (model down) → keep original.
            if name_source in _WEAK_SOURCES and _looks_messy(name):
                from engine.extract.llm import normalize_name_llm

                cleaned = normalize_name_llm(name)
                if cleaned:
                    name, name_source = cleaned, "llm_normalized"
            sessions.append(
                Session(name=name, info_url=r["info_url"],
                        register_url=rr.register_url, dates=r.get("dates", ""),
                        ages=r.get("ages", ""), price=r.get("price", ""),
                        extractor="generic", name_source=name_source,
                        raw_name=r["name"], nearest_hub=nh,
                        register_is_info=rr.register_is_info,
                        register_confidence=rr.confidence, page_role=role)
            )
        programs = group_sessions_into_programs(provider, sessions, camp_scoped=False)
        return ExtractResult(programs=programs, fetch_log=fetch.log)
