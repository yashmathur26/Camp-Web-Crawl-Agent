"""Part C ↔ Engine v3 bridge.

Part C's discovery/audit/registry layers live in src/ (never rebuilt), but two
things must come from the ENGINE, not the old pipeline:

1. The audit base: engine sessions.csv (clean, gated rows) instead of the old
   pipeline's camp_sessions.csv.
2. Enumeration of newly-discovered hosts: fingerprint the vendor (engine
   proposer signatures) and run the engine extractor + gate per provider —
   never the old enumerate_town.

Sessions are returned in the old session-dict shape so the rest of Part C
(categorizer, registry, matrix, verify bookkeeping) is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def engine_sessions_for_town(town: str) -> list[dict]:
    """Load the engine's published sessions for a town in old-pipeline shape."""
    path = Path("data") / town.lower() / "engine" / "sessions.csv"
    if not path.exists():
        return []
    import csv

    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            verdict = r.get("verdict", "")
            out.append(
                {
                    "name": r.get("name", ""),
                    "register_url": r.get("register_url", ""),
                    "info_url": r.get("info_url", ""),
                    "dates": r.get("dates", ""),
                    "ages": r.get("ages", ""),
                    "price": r.get("price", ""),
                    "platform": r.get("extractor", "engine"),
                    "source_url": r.get("info_url", ""),
                    "kind": "session",
                    # engine info_confirmed == parent-findable for Part C
                    "parent_verdict": "parent_ready" if verdict == "parent_ready"
                    else ("info_confirmed" if verdict == "info_confirmed" else verdict),
                }
            )
    return out


async def _extract_one(provider, fetch):
    from engine.extract.base import extract_for_provider
    from engine.validate.gate import gate_program

    programs, gap, fetched_text = await extract_for_provider(provider)
    sessions = []
    for program in programs:
        result = gate_program(program, fetched_text=fetched_text,
                              provider_id=provider.provider_id)
        sessions.extend(result.published)
    return sessions, gap


def enumerate_hosts_via_engine(town: str, urls: list[str]) -> list[dict]:
    """Engine-extract a batch of newly discovered seed URLs. Returns sessions
    in old-pipeline dict shape. One provider failing never kills the batch."""
    from engine.model import Provider
    from engine.registry.proposer import fingerprint_vendor

    async def run() -> list[dict]:
        from engine.extract.base import reset_shared_client, shared_client

        reset_shared_client()
        fetch = shared_client()
        out: list[dict] = []
        seen_hosts: set[str] = set()
        for url in urls:
            host = urlparse(url).netloc.lower().replace("www.", "")
            if not host or host in seen_hosts:
                continue
            seen_hosts.add(host)
            # Vendor fingerprint from the seed page's links (engine proposer).
            try:
                _text, links, _html = fetch.fetch_text(url)
            except Exception:  # noqa: BLE001
                links = []
            vendor, org_id, _evidence = fingerprint_vendor(url, links, host)
            provider = Provider(name=host, host=host, town=town, seed_url=url,
                                vendor=vendor, org_id=org_id)
            try:
                sessions, gap = await _extract_one(provider, fetch)
            except Exception as exc:  # noqa: BLE001
                logger.warning("engine bridge: %s failed: %s", host, exc)
                continue
            if gap:
                logger.info("engine bridge gap [%s]: %s — %s", host, gap.reason,
                            gap.evidence[:100])
            for s in sessions:
                out.append(
                    {
                        "name": s.name, "register_url": s.register_url,
                        "info_url": s.info_url, "dates": s.dates, "ages": s.ages,
                        "price": s.price, "platform": s.extractor or "engine",
                        "source_url": url, "kind": "session",
                        "parent_verdict": "parent_ready" if s.verdict == "parent_ready"
                        else "info_confirmed",
                    }
                )
        return out

    return asyncio.run(run())
