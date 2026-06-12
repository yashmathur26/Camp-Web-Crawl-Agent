"""Enrollsy extractor (task 4.4). app.enrollsy.com/enroll/{org} is a SPA
(~574 chars static). Probe rendered; if it stays thin → the marketing site via
the generic path (Waldorf's /summer page carries the program); nothing →
gap: render_failed."""

from __future__ import annotations

from engine.extract.base import ExtractResult, Extractor
from engine.fetch.client import Budget, FetchClient
from engine.model import Gap, Provider


class EnrollsyExtractor(Extractor):
    vendor = "enrollsy"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        from engine.extract.generic import GenericExtractor
        from engine.fetch.render import fetch_rendered

        budget = Budget()
        portal = (
            f"https://app.enrollsy.com/enroll/{provider.org_id}" if provider.org_id else ""
        )
        if not portal:
            _t, links, _h = fetch.fetch_text(provider.seed_url, budget=budget)
            for l in links:
                if "enrollsy.com" in l.get("url", "").lower():
                    portal = l["url"]
                    break

        portal_gap = None
        if portal:
            text, _l, _h = await fetch_rendered(portal, cache=fetch.cache, log=fetch.log)
            if len(text.strip()) < 400:
                portal_gap = Gap(
                    provider_id=provider.provider_id, reason="render_failed",
                    evidence=f"enrollsy SPA stayed thin after render: {portal}",
                    suggested_action="inspect for a JSON config endpoint",
                )

        generic = await GenericExtractor().extract(provider, fetch)
        if generic.programs:
            return ExtractResult(programs=generic.programs, gap=portal_gap, fetch_log=fetch.log)
        return ExtractResult(
            gap=portal_gap or generic.gap,
            fetch_log=fetch.log,
        )
