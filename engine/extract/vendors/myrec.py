"""MyRec extractor — REWRITE (task 3.4), not a port of the old behavior.

The catalog listings (/info/activities/default.aspx?type=camps, type=activities,
activities.aspx) are server-rendered rows carrying name + ProgramID + often
dates/ages in the link text. The detail pages (program_details.aspx?ProgramID=)
are 171-char JS shells on the plain path — NEVER bulk-fetched (old cost:
~25 wasted minutes/town).

info_url decision (task 2.4 spike, recorded): a rendered detail page yields
10,685 chars in ~5.4s → detail pages ARE the info_urls, rendered per-publish
through fetch/render.py (cached). Sessions whose detail render doesn't fit the
provider budget fall back to the camp listing page as info_url (also valid:
server-rendered, carries the program name). Expected verdicts: info_confirmed.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from engine.extract.base import ExtractResult, Extractor, group_sessions_into_programs
from engine.fetch.client import Budget, BudgetExceeded, FetchClient
from engine.fetch.urls import normalize_url
from engine.model import Gap, Program, Provider, Session

_AGES_RE = re.compile(r"ages?\s*:?\s*\d{1,2}(?:\s*[-–&]\s*\d{1,2})?(?:\s*\+)?", re.I)
_DATES_RE = re.compile(
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{1,2}"
    r"(?:[a-z]{2})?(?:\s*[-–—]\s*(?:[a-z]+\.?\s*)?\d{1,2}(?:[a-z]{2})?)?",
    re.I,
)
# Listing chrome that is not a program (ported judgment from Phase 0 GT work).
_NON_PROGRAM_RE = re.compile(
    r"^(?:view|more|details|register|search|calendar|login|sign in|home)$", re.I
)


def parse_listing_links(links: list[dict]) -> dict[str, dict]:
    """ProgramID → {name, url, dates, ages} from server-rendered listing rows."""
    out: dict[str, dict] = {}
    for link in links:
        url = link.get("url", "")
        if "program_details.aspx" not in url.lower():
            continue
        qs = {k.lower(): v for k, v in parse_qs(urlparse(url).query).items()}
        pid = (qs.get("programid") or [""])[0]
        text = re.sub(r"\s+", " ", (link.get("text") or "")).strip()
        if not pid or not text or _NON_PROGRAM_RE.match(text):
            continue
        entry = out.setdefault(
            pid, {"name": "", "url": normalize_url(url), "dates": "", "ages": ""}
        )
        if len(text) > len(entry["name"]):
            entry["name"] = text
        if not entry["dates"]:
            m = _DATES_RE.search(text)
            if m:
                entry["dates"] = m.group(0)
        if not entry["ages"]:
            m = _AGES_RE.search(text)
            if m:
                entry["ages"] = m.group(0)
    return {pid: e for pid, e in out.items() if e["name"]}


class MyrecExtractor(Extractor):
    vendor = "myrec"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        from config_engine import ENGINE
        budget = Budget(seconds=float(ENGINE["render_heavy_budget_s"]))
        parsed = urlparse(provider.seed_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        camps_listing = f"{base}/info/activities/default.aspx?type=camps"
        listings = [
            camps_listing,
            f"{base}/info/activities/activities.aspx",
            f"{base}/info/activities/default.aspx?type=activities",
        ]

        all_rows: dict[str, dict] = {}
        for listing in listings:
            _text, links, _ = fetch.fetch_text(listing, budget=budget)
            for pid, row in parse_listing_links(links).items():
                all_rows.setdefault(pid, row)

        if not all_rows:
            return ExtractResult(
                gap=Gap(
                    provider_id=provider.provider_id, reason="empty",
                    evidence=f"no program_details rows on {listings[0]}",
                    suggested_action="check listing URLs / render the listing",
                ),
                fetch_log=fetch.log,
            )

        # Phase-3 live-run finding: MyRec's type=camps listing returns the FULL
        # activities catalog (adult fitness included) — it is NOT camp-scoped.
        # Never set camp_scoped here; every row earns publication through
        # evidence the gate can verify (R4.1):
        #   - rows whose listing text carried ages/dates → listing is info_url
        #     (fetched this run, contains the name); fields carry the evidence.
        #   - rows without listing evidence → render the detail page (2.4 spike)
        #     so the gate can read per-program evidence; youth-looking rows
        #     first (scheduling priority only, never keep/drop). Un-rendered
        #     leftovers keep info_url="" and gap as not-fetched (R4.4).
        from engine.fetch.render import fetch_rendered

        with_evidence = {p: r for p, r in all_rows.items() if r["dates"] or r["ages"]}
        need_render = {p: r for p, r in all_rows.items() if p not in with_evidence}

        def _render_priority(row: dict) -> int:
            text = row["name"].lower()
            score = 0
            if re.search(r"camp|clinic|youth|kids?|junior|pre-?k|grade", text):
                score -= 2
            if re.search(r"senior|adult|fitness|yoga|pilates|tai chi|bingo", text):
                score += 2
            return score

        sessions: list[Session] = []
        for pid, row in with_evidence.items():
            sessions.append(
                Session(
                    name=row["name"], info_url=camps_listing,
                    register_url=row["url"], dates=row["dates"],
                    ages=row["ages"], extractor=self.vendor,
                )
            )
        for pid, row in sorted(need_render.items(), key=lambda kv: _render_priority(kv[1])):
            info_url = ""
            try:
                budget.check()
                text, _links, _ = await fetch_rendered(
                    row["url"], cache=fetch.cache, log=fetch.log
                )
                if len(text) >= 400:
                    info_url = row["url"]
                    # Field enrichment — RANGES only: every LexRec detail page
                    # carries a bare "June 1st" (registration-opens boilerplate)
                    # which is not program evidence (round-2 leak).
                    if not row["dates"]:
                        dm = _DATES_RE.search(text)
                        if dm and re.search(r"[-–—]|\bto\b", dm.group(0)):
                            row["dates"] = dm.group(0)
                    if not row["ages"]:
                        am = re.search(
                            r"ages?\s*:?\s*\d{1,2}\s*(?:[-–&]|and|to)\s*(?:\d{1,3}|up)",
                            text[:6000], re.I,
                        ) or _AGES_RE.search(text[:4000])
                        if am:
                            row["ages"] = am.group(0)
            except BudgetExceeded:
                pass
            sessions.append(
                Session(
                    name=row["name"], info_url=info_url,
                    register_url=row["url"], dates=row["dates"],
                    ages=row["ages"], extractor=self.vendor,
                )
            )

        programs = group_sessions_into_programs(provider, sessions, camp_scoped=False)
        return ExtractResult(programs=programs, fetch_log=fetch.log)
