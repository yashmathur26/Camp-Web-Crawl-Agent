"""Sawyer (hisawyer.com) extractor (task 4.1).

The provider's marketing page pairs each program heading with its Sawyer
activity-set link (hisawyer.com/{org}/schedules/activity-set/{id}) — the
activity-set page is the info_url. Programs are read from the marketing page
(deterministic heading→link pairing, same approach validated in Phase 0 GT
collection); activity-set pages are fetched within budget so the gate's
invariant can verify them.
"""

from __future__ import annotations

import re

from engine.extract.base import ExtractResult, Extractor
from engine.fetch.client import Budget, BudgetExceeded, FetchClient
from engine.model import Gap, Program, Provider, Session

_ASET_RE = re.compile(r"hisawyer\.com/([\w-]+)/schedules/activity-set/(\d+)")
_HEAD_RE = re.compile(r"<h[1-4][^>]*>([\s\S]*?)</h[1-4]>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_NOISE_HEAD_RE = re.compile(
    r"summer camps|new for|returning favorites|program details|frequently asked|"
    r"add-on|stay connected|unlock|we make",
    re.I,
)
_GRADES_RE = re.compile(r"(?:gr|grades?)\.?\s*:?\s*(?:rising\s*)?[k0-9][\s\-–toandk0-9]{0,12}", re.I)


def pair_headings_to_sets(html: str) -> list[dict]:
    """Each qualifying heading pairs with the next activity-set link after it."""
    heads = [
        (m.start(), re.sub(r"\s+", " ", _TAG_RE.sub(" ", m.group(1))).strip())
        for m in _HEAD_RE.finditer(html or "")
    ]
    links = [(m.start(), m.group(0), m.group(2)) for m in _ASET_RE.finditer(html or "")]
    seen: set[str] = set()
    out = []
    for pos, name in heads:
        if not name or len(name) > 70 or _NOISE_HEAD_RE.search(name):
            continue
        following = [(p, frag, sid) for p, frag, sid in links if p > pos]
        if not following:
            continue
        _p, frag, set_id = following[0]
        if set_id in seen:
            continue
        seen.add(set_id)
        g = _GRADES_RE.search(name)
        out.append(
            {"name": name, "set_id": set_id,
             "info_url": "https://www." + frag if not frag.startswith("http") else frag,
             "ages": g.group(0).strip() if g else ""}
        )
    return out


class SawyerExtractor(Extractor):
    vendor = "sawyer"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        budget = Budget()
        _text, _links, html = fetch.fetch_text(provider.seed_url, budget=budget)
        if not html:
            # Cache hits return text only; heading pairing needs raw HTML.
            # TODO(cleanup): cache raw html alongside text.
            try:
                html = fetch._client.get(provider.seed_url).text  # noqa: SLF001
            except Exception:  # noqa: BLE001
                html = ""
        rows = pair_headings_to_sets(html)
        if not rows:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="empty",
                        evidence=f"no heading→activity-set pairs on {provider.seed_url}",
                        suggested_action="check the marketing page / sawyer org id"),
            )

        programs: list[Program] = []
        for r in rows:
            # Fetch the activity-set info page (plain path; hisawyer serves
            # ~4-5KB server-rendered) within budget; the gate verifies it.
            try:
                fetch.fetch_text(r["info_url"], budget=budget)
            except BudgetExceeded:
                pass
            prog = Program(
                name=r["name"], provider_id=provider.provider_id,
                info_url=r["info_url"], camp_scoped=True,  # summer-camp page roster (R4.2)
            )
            prog.sessions = [
                Session(name=r["name"], info_url=r["info_url"],
                        register_url=r["info_url"], ages=r["ages"],
                        extractor=self.vendor, program_id=prog.program_id)
            ]
            programs.append(prog)
        return ExtractResult(programs=programs, fetch_log=fetch.log)
