"""Generic long-tail extractor (task 5.2, plan §7) — vendor: unknown.

Pipeline: rendered seed -> deterministic harvest (JSON-LD, heading+evidence
clusters) -> bounded same-host follow (depth<=2, scored, media refused,
budgeted) -> LLM extraction (R3, fail open) -> candidates to the gate.
Thin/blocked/empty -> diagnosed gap, ZERO LLM calls.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from config_engine import ENGINE
from engine.extract.base import ExtractResult, Extractor, group_sessions_into_programs
from engine.fetch.client import Budget, BudgetExceeded, FetchClient
from engine.fetch.urls import is_media_url, normalize_url
from engine.model import Gap, Program, Provider, Session

_JSONLD_RE = re.compile(r'<script[^>]+ld\+json[^>]*>([\s\S]*?)</script>', re.I)
_EVENT_TYPES = {"event", "childrensevent", "course", "educationevent", "camp"}
# Ported crawl_link_score essence: follow-worthy paths on a camp site.
_FOLLOW_RE = re.compile(r"camp|summer|program|clinic|register|enroll|class", re.I)
_SKIP_RE = re.compile(r"about|contact|faq|donate|news|blog|gallery|privacy|login|account", re.I)
# Sections that never lead to youth summer camps (ported junk-path knowledge +
# the YMCA/JCC/LifeTime feedback round): fitness floors, weight loss, adult
# wellness, after-school/childcare, membership. Absolute skips for follow AND
# record scoping — even when the path also says "program" or "class".
_NONCAMP_SECTION_RE = re.compile(
    r"fitness|health-?wellness|weight-?loss|weightloss|wellness|after-?school|"
    r"enrichment|child-?care|child-?watch|membership|personal-?train|massage|"
    r"aquatics|group-?exercise|find-a?-?program|adult|education-care",
    re.I,
)
_CAMP_PATH_RE = re.compile(r"camp|summer", re.I)
_DATES_RE = re.compile(
    r"(?:june|july|august)\s*\d{1,2}(?:[a-z]{2})?(?:\s*[-–]\s*(?:[a-z]+\s*)?\d{1,2}(?:[a-z]{2})?)?"
    r"|\b[678]/\d{1,2}\s*[-–]\s*[678]?/?\d{1,2}\b", re.I)
_AGES_RE = re.compile(r"ages?\s*:?\s*\d{1,2}\s*(?:[-–to&]+\s*\d{1,2})?|grades?\s*:?\s*(?:pre)?[k0-9][-–k0-9 ]{0,8}|preschool|pre-k", re.I)


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
                                "ages": "", "price": ""})
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
    return campy if campy else records


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

        # Bounded follow: depth 1 (seed children); collect per-page candidates.
        pages: list[tuple[str, str]] = [(provider.seed_url, text)]
        for u in score_follow_links(provider.seed_url, links):
            try:
                budget.check()
            except BudgetExceeded:
                break
            ptext, _pl, phtml = fetch.fetch_text(u, budget=budget)
            if len(ptext.strip()) >= 400:
                pages.append((u, ptext))
                records.extend({**e, "info_url": u} for e in jsonld_events(phtml))

        # LLM extraction on substantive pages (R3; fail OPEN on None).
        if not records:
            from engine.extract.llm import extract_programs

            for u, ptext in pages[:4]:
                got = extract_programs(ptext, u, provider.town)
                if got is None:
                    continue  # model failure — deterministic results stand
                records.extend({**r, "info_url": u} for r in got)

        # Deterministic enrichment: pull dates/ages evidence from page text.
        for r in records:
            page_text = next((t for u, t in pages if u == r["info_url"]), "")
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

        seen: set[str] = set()
        sessions = []
        for r in records:
            key = r["name"].lower().strip()
            if key in seen:
                continue
            seen.add(key)
            sessions.append(
                Session(name=r["name"], info_url=r["info_url"],
                        register_url=r["info_url"], dates=r.get("dates", ""),
                        ages=r.get("ages", ""), price=r.get("price", ""),
                        extractor="generic")
            )
        programs = group_sessions_into_programs(provider, sessions, camp_scoped=False)
        return ExtractResult(programs=programs, fetch_log=fetch.log)
