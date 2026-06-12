"""CampBrain extractor (task 4.3). {org}.campbrainregistration.com sits behind
a queue-it throttle. Attempt the portal rendered (realistic UA via the shared
render path); still throttled → gap: blocked with evidence — AND merge whatever
the generic path harvests from the provider's own marketing site, so Summers
Edge yields programs or a diagnosed gap, never an empty-name row."""

from __future__ import annotations

import re

from engine.extract.base import ExtractResult, Extractor
from engine.fetch.client import Budget, FetchClient
from engine.model import Gap, Provider

_QUEUE_RE = re.compile(r"queueittoken|queue-it", re.I)


class CampbrainExtractor(Extractor):
    vendor = "campbrain"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        from engine.extract.generic import GenericExtractor
        from engine.fetch.render import fetch_rendered

        budget = Budget()
        # Locate the portal from registry org_id or the marketing page's links.
        portal = (
            f"https://{provider.org_id}.campbrainregistration.com" if provider.org_id else ""
        )
        _t, links, html = fetch.fetch_text(provider.seed_url, budget=budget)
        if not portal:
            for l in links:
                if "campbrain" in l.get("url", "").lower():
                    portal = l["url"]
                    break

        portal_gap = None
        if portal:
            text, _l, phtml = await fetch_rendered(portal, cache=fetch.cache, log=fetch.log)
            if len(text.strip()) < 400 or _QUEUE_RE.search(phtml or text):
                portal_gap = Gap(
                    provider_id=provider.provider_id, reason="blocked",
                    evidence=f"campbrain portal throttled/thin ({len(text.strip())} chars,"
                             f" queue-it={'yes' if _QUEUE_RE.search(phtml or text) else 'no'}): {portal}",
                    suggested_action="retry off-peak; rely on marketing-site programs",
                )
            # A rendered portal with real content flows through generic harvest
            # below (its page is in the run cache for the gate).

        generic = await GenericExtractor().extract(provider, fetch)
        if generic.programs:
            return ExtractResult(programs=generic.programs, gap=portal_gap, fetch_log=fetch.log)
        return ExtractResult(
            gap=portal_gap or generic.gap or Gap(
                provider_id=provider.provider_id, reason="needs_review",
                evidence="no portal and no marketing-site programs",
                suggested_action="manual review",
            ),
            fetch_log=fetch.log,
        )
