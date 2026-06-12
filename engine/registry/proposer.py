"""Registry proposer (Phase 6, tasks 6.1/6.2): discovery → PROPOSALS, never a
crawl set. Output is towns/<town>.proposals.yaml with evidence per candidate;
a human reviews and promotes entries into towns/<town>.yaml (see
REGISTRY_REVIEW.md). The proposer never writes towns/<town>.yaml directly.

Vendor fingerprinting is ported from scripts/fingerprint_providers.py's
signature idea: detect the registration platform from the seed page's links.
Search-engine discovery is pluggable (search_fn) so the core is testable
offline; wire a real provider at the CLI (`engine propose --town X`).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from engine.fetch.client import FetchClient
from engine.registry.schema import TOWNS_DIR

# host-substring → vendor (ported fingerprint signatures)
VENDOR_SIGNATURES = (
    ("myvscloud.com", "webtrac"),
    ("webtrac", "webtrac"),
    ("myrec.com", "myrec"),
    ("campscui.active.com", "active"),
    ("activecommunities.com", "active"),
    ("hisawyer.com", "sawyer"),
    ("campbrainregistration.com", "campbrain"),
    ("campbrain.com", "campbrain"),
    ("enrollsy.com", "enrollsy"),
    ("daxko.com", "daxko"),
    ("recdesk.com", "recdesk"),
    ("civicrec", "civicrec"),
    ("communitypass.net", "communitypass"),
    ("ultracamp.com", "ultracamp"),
)

_DENY_HOST_RE = re.compile(
    r"facebook|instagram|youtube|twitter|x\.com|yelp|tripadvisor|"
    r"activityhero|macaronikid|mommypoppins|care\.com|niche\.com|yellowpages",
    re.I,
)


def fingerprint_vendor(seed_url: str, links: list[dict], host: str) -> tuple[str, str, str]:
    """Return (vendor, org_id_hint, evidence_url)."""
    if "communityed" in host:
        return "communityed", host.split(".")[0], seed_url
    candidates = [seed_url] + [l.get("url", "") for l in links]
    for u in candidates:
        low = u.lower()
        for sub, vendor in VENDOR_SIGNATURES:
            if sub in low:
                org = ""
                netloc = urlparse(u).netloc.lower()
                if vendor == "webtrac" and netloc.endswith("myvscloud.com"):
                    org = netloc.split(".")[0]
                elif vendor == "myrec":
                    org = netloc.split(".")[0]
                elif vendor == "active":
                    m = re.search(r"/orgs/([\w-]+)", u)
                    org = m.group(1) if m else ""
                elif vendor == "sawyer":
                    m = re.search(r"hisawyer\.com/([\w-]+)", low)
                    org = m.group(1) if m else ""
                return vendor, org, u
    return "unknown", "", ""


def propose_town(
    town: str,
    state: str,
    candidate_urls: list[str],
    *,
    fetch: FetchClient | None = None,
) -> Path:
    """Fingerprint candidate seed URLs into a proposals file for human review."""
    fetch = fetch or FetchClient()
    proposals = []
    seen_hosts: set[str] = set()
    for url in candidate_urls:
        host = urlparse(url).netloc.lower().replace("www.", "")
        if not host or host in seen_hosts or _DENY_HOST_RE.search(host):
            continue
        seen_hosts.add(host)
        text, links, _ = fetch.fetch_text(url)
        vendor, org, evidence = fingerprint_vendor(url, links, host)
        proposals.append(
            {"name": host, "host": host, "seed": url, "vendor": vendor,
             "org_id": org,
             "evidence": evidence or f"fetched {len(text)} chars",
             "status": "proposed"}
        )
    out = TOWNS_DIR / f"{town.lower()}.proposals.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.safe_dump(
            {"town": town, "state": state, "review": "REQUIRED — promote approved "
             "entries into towns/<town>.yaml by hand (see REGISTRY_REVIEW.md)",
             "providers": proposals},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return out
