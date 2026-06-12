"""Daxko extractor (task 4.5) — _extract_daxko_sessions PORTED from
src/platforms.py with its swim-test exclusion. ProgramsV2 listing links carry
program names; detail pages are the info_urls."""

from __future__ import annotations

import re

from engine.extract.base import ExtractResult, Extractor, group_sessions_into_programs
from engine.fetch.client import Budget, FetchClient
from engine.fetch.urls import normalize_url
from engine.model import Gap, Provider, Session

_DETAIL_RE = re.compile(
    r"ProgramDetail\.mvc|OfferingDetail\.mvc|program_id=\d+|offering_id=\d+", re.I
)
_NOISE_RE = re.compile(
    r"swim\s*test|life\s*jacket|pre[\s-]?camp\s*test|fitting|membership|donat", re.I
)


def extract_daxko_sessions(links: list[dict], source_url: str) -> list[dict]:
    """One row per detail link; swim-test/membership noise excluded (ported)."""
    by_key: dict[str, dict] = {}
    for link in links:
        u = link.get("url", "")
        if "daxko.com" not in u.lower() or not _DETAIL_RE.search(u):
            continue
        text = re.sub(r"\s+", " ", (link.get("text") or "")).strip()
        if not text or _NOISE_RE.search(text):
            continue
        key = normalize_url(u)
        if key not in by_key or len(text) > len(by_key[key]["name"]):
            by_key[key] = {"name": text, "register_url": key, "source": source_url}
    return list(by_key.values())


class DaxkoExtractor(Extractor):
    vendor = "daxko"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        budget = Budget()
        _t, links, _h = fetch.fetch_text(provider.seed_url, budget=budget)
        portals = [l["url"] for l in links if "daxko.com" in l.get("url", "").lower()]
        rows: list[dict] = []
        for portal in dict.fromkeys(portals)[:4] if portals else []:
            _pt, plinks, _ph = fetch.fetch_text(portal, budget=budget)
            rows.extend(extract_daxko_sessions(plinks, portal))
        if not rows:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="empty",
                        evidence=f"no daxko detail rows from {provider.seed_url}",
                        suggested_action="check portal links / season"),
            )
        sessions = []
        for r in rows:
            fetch.fetch_text(r["register_url"], budget=budget)  # info-url invariant
            sessions.append(Session(name=r["name"], info_url=r["register_url"],
                                    register_url=r["register_url"], extractor=self.vendor))
        return ExtractResult(
            programs=group_sessions_into_programs(provider, sessions, camp_scoped=False),
            fetch_log=fetch.log,
        )
