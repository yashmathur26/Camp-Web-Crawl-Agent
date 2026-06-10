"""Parent auditor for agentic Phase C gap detection."""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from config.gap_taxonomy import GAP_CATEGORIES, GAP_SEARCH_TEMPLATES
from config.prompts import PARENT_AUDITOR_SYSTEM
from config.settings import SETTINGS, STATE
from src.data_layout import camp_links_csv
from src.llm import OllamaError, chat, is_available
from src.session_quality import split_parent_verdicts

logger = logging.getLogger(__name__)


def _category_from_session(session: dict) -> str | None:
    blob = " ".join(
        x.lower()
        for x in (
            session.get("name", ""),
            session.get("platform", ""),
            session.get("register_url", ""),
        )
    )
    for cat in GAP_CATEGORIES:
        if cat.replace("_", " ") in blob or cat in blob:
            return cat
    if any(w in blob for w in ("sport", "soccer", "basketball", "tennis")):
        return "sports"
    if any(w in blob for w in ("art", "craft", "paint")):
        return "arts"
    if any(w in blob for w in ("robot", "code", "stem", "lego")):
        return "stem"
    return None


def _load_camp_link_hosts(town: str, path: Path | str | None = None) -> set[str]:
    path = path or camp_links_csv()
    hosts: set[str] = set()
    p = Path(path)
    if not p.exists():
        return hosts
    with open(p, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("town_hint") and row.get("town_hint") != town:
                continue
            url = row.get("url", "")
            if not url:
                continue
            h = urlparse(url).netloc.lower().replace("www.", "")
            if h:
                hosts.add(h)
    return hosts


def _rule_based_holes(
    town: str,
    sessions: list[dict],
    known_hosts: set[str],
) -> list[dict]:
    buckets = split_parent_verdicts(sessions)
    parent_ready = buckets["parent_ready"]
    holes: list[dict] = []

    covered: set[str] = set()
    for s in parent_ready:
        cat = _category_from_session(s)
        if cat:
            covered.add(cat)
    for cat in GAP_CATEGORIES:
        if cat not in covered:
            tpl = GAP_SEARCH_TEMPLATES.get(cat)
            if tpl:
                holes.append(
                    {
                        "hole_id": f"missing_category_{cat}",
                        "type": "missing_category",
                        "priority": 3,
                        "search_query": tpl.format(town=town, state=STATE),
                        "rationale": f"No parent_ready sessions for category {cat}",
                    }
                )

    ready_by_host: Counter = Counter()
    all_by_host: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        reg = s.get("register_url") or s.get("source_url", "")
        h = urlparse(reg).netloc.lower().replace("www.", "")
        if h:
            all_by_host[h].append(s)
        if s.get("parent_verdict") == "parent_ready":
            ready_by_host[h] += 1

    for host in sorted(known_hosts):
        if ready_by_host.get(host, 0) == 0:
            holes.append(
                {
                    "hole_id": f"missing_provider_{host.replace('.', '_')[:40]}",
                    "type": "missing_provider",
                    "priority": 2,
                    "search_query": f"{town} {STATE} {host.split('.')[0]} summer camp registration",
                    "rationale": f"Known host {host} has no parent_ready sessions",
                }
            )

    for host, group in all_by_host.items():
        if not group:
            continue
        verdicts = {s.get("parent_verdict") for s in group}
        if verdicts <= {"brochure_only", "unverified"} and len(group) >= 2:
            holes.append(
                {
                    "hole_id": f"brochure_gap_{host.replace('.', '_')[:40]}",
                    "type": "brochure_gap",
                    "priority": 2,
                    "search_query": f"{town} {STATE} {host} summer camp register online",
                    "rationale": f"Provider {host} has sessions but none parent_ready",
                }
            )

    failed_hosts = {
        urlparse(s.get("register_url", "")).netloc.lower().replace("www.", "")
        for s in buckets["fetch_failed"]
    }
    for host in sorted(failed_hosts):
        if host and ready_by_host.get(host, 0) == 0:
            holes.append(
                {
                    "hole_id": f"failed_enrollment_{host.replace('.', '_')[:40]}",
                    "type": "failed_enrollment",
                    "priority": 1,
                    "search_query": f"{town} {STATE} {host.split('.')[0]} youth summer camp registration catalog",
                    "rationale": f"Enrollment verification failed for {host}",
                }
            )

    holes.sort(key=lambda h: h.get("priority", 5))
    return holes


def _llm_refine_holes(town: str, sessions: list[dict], rule_holes: list[dict]) -> list[dict]:
    if not is_available():
        return rule_holes
    buckets = split_parent_verdicts(sessions)
    summary = {
        "town": town,
        "state": STATE,
        "parent_ready": len(buckets["parent_ready"]),
        "brochure_only": len(buckets["brochure_only"]),
        "total_sessions": len(sessions),
        "rule_holes": rule_holes[:20],
        "sample_parent_ready": [
            s.get("name", "") for s in buckets["parent_ready"][:15]
        ],
        "missing_categories": [
            h["hole_id"].replace("missing_category_", "")
            for h in rule_holes
            if h.get("type") == "missing_category"
        ][:10],
    }
    try:
        resp = chat(
            PARENT_AUDITOR_SYSTEM,
            json.dumps(summary, ensure_ascii=False),
            model=SETTINGS.get("ollama_verify_model") or SETTINGS.get("ollama_model"),
            temperature=0.2,
            timeout=60,
        )
        llm_holes = resp.get("holes", [])
        if not llm_holes:
            return rule_holes
        merged = {h["hole_id"]: h for h in rule_holes}
        for h in llm_holes:
            hid = h.get("hole_id") or f"llm_{len(merged)}"
            if hid not in merged and h.get("search_query"):
                merged[hid] = {
                    "hole_id": hid,
                    "type": h.get("type", "missing_category"),
                    "priority": int(h.get("priority", 3)),
                    "search_query": str(h["search_query"]),
                    "rationale": h.get("rationale", "LLM auditor"),
                }
        out = sorted(merged.values(), key=lambda x: x.get("priority", 5))
        return out
    except OllamaError as exc:
        logger.warning("parent auditor LLM failed: %s", exc)
        return rule_holes


def audit_catalog(
    town: str,
    sessions: list[dict],
    *,
    camp_links_path: Path | str | None = None,
    use_llm: bool = True,
) -> dict:
    known_hosts = _load_camp_link_hosts(town, camp_links_path)
    rule_holes = _rule_based_holes(town, sessions, known_hosts)
    holes = _llm_refine_holes(town, sessions, rule_holes) if use_llm else rule_holes
    buckets = split_parent_verdicts(sessions)
    ready = len(buckets["parent_ready"])
    total = len(sessions) or 1
    coverage = round(ready / total, 2)
    return {
        "town": town,
        "holes": holes,
        "coverage_score": coverage,
        "parent_ready": ready,
        "total_sessions": len(sessions),
    }
