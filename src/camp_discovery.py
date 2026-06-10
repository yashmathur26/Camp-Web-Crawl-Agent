"""Broad camp-like link discovery + per-page verification for Phase B.5.

Structured adapters (/class/, /program/, WebTrac, etc.) run first. This module
supplements them by scoring every promising link on a provider site, fetching
candidate pages, and verifying with rules + tiered LLM.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from config.settings import SETTINGS
from src.filter_links import is_likely_camp_link
from src.registration import is_camp_catalog_url, is_registration_platform_url
from src.urls import normalize_url

logger = logging.getLogger(__name__)

_SUMMER_CAMP_SIGNAL = re.compile(
    r"camp|camps|summer|clinic|clinics|academy|vacation|lexplor|"
    r"day\s*camp|sport|sports|swim|stem|workshop|week\s*\d|"
    r"register|enroll|sign\s*up|grader?|ages?\s*\d|multi[\s-]?sport|"
    r"specialty|playground|recreation|sacc|cit\b|lit\b|baseball|basketball|"
    r"soccer|lacrosse|flag\s*football|gymnastics|tennis",
    re.I,
)

_STRONG_CAMP_SIGNAL = re.compile(
    r"summer\s*camp|day\s*camp|sport\s*camp|camp\s*program|"
    r"summer\s*program|youth\s*camp|vacation\s*camp|lexplor|sport\s*camps",
    re.I,
)

_DROP_CANDIDATE_RE = re.compile(
    r"/(login|signin|cart|privacy|terms|contact|employment|career|donate|"
    r"membership|news|blog|gallery|photo|faq|about-us|calendar)(/|$|\?)|"
    r"\.(pdf|jpg|jpeg|png|gif|css|js)(\?|$)|"
    r"mailto:|tel:|#",
    re.I,
)

_COMMON_SUMMER_PATHS = (
    "/summer",
    "/summer-camp",
    "/summer-camps",
    "/camps",
    "/camp",
    "/summer-programs",
    "/about/summer-programs",
    "/about/summer-programs/sport-camps",
    "/programs/summer",
    "/recreation/summer",
    "/youth/summer",
    "/info/activities",
    "/info/activities/activities.aspx",
)


def score_camp_candidate(url: str, text: str = "") -> int:
    if not url or _DROP_CANDIDATE_RE.search(url):
        return 0
    combined = f"{url} {text or ''}"
    if not _SUMMER_CAMP_SIGNAL.search(combined):
        return 0
    score = 1
    if _STRONG_CAMP_SIGNAL.search(combined):
        score += 3
    if re.search(r"register|enroll|sign[\s-]?up|program_details|iteminfo", combined, re.I):
        score += 2
    path = urlparse(url).path.lower()
    if re.search(r"/(camp|class|program|course|activity|session)s?/", path):
        score += 1
    if re.search(
        r"after\s*care|before\s*care|swim\s*test|life\s*jacket|pre[\s-]?camp\s*test",
        combined,
        re.I,
    ):
        score -= 4
    return max(0, score)


def collect_camp_candidate_links(
    seed_url: str,
    links: list[dict],
    *,
    allow_off_domain_registration: bool = True,
) -> list[dict]:
    """Rank same-host and registration-platform links that smell like summer camps."""
    from src.filter_links import _is_denylisted

    seed_host = urlparse(seed_url).netloc.lower().replace("www.", "")
    seen: set[str] = set()
    scored: list[tuple[int, dict]] = []

    def consider(u: str, text: str) -> None:
        nu = normalize_url(u)
        if not nu or nu in seen or _is_denylisted(nu):
            return
        host = urlparse(nu).netloc.lower().replace("www.", "")
        same_host = host == seed_host
        off_reg = allow_off_domain_registration and is_registration_platform_url(nu)
        if not same_host and not off_reg:
            return
        if off_reg and not is_camp_catalog_url(nu):
            return
        s = score_camp_candidate(nu, text)
        if s <= 0:
            return
        if same_host and s < 3 and not is_likely_camp_link(nu, text):
            return
        seen.add(nu)
        scored.append((s, {"url": nu, "text": text or ""}))

    for link in links:
        consider(link.get("url", ""), link.get("text", ""))

    scored.sort(key=lambda x: (-x[0], x[1]["url"]))
    return [item for _, item in scored]


async def discover_verified_sessions(
    seed_url: str,
    links: list[dict],
    *,
    town_hint: str = "",
    existing_register_urls: set[str] | None = None,
) -> list[dict]:
    """Find camp-like links, fetch pages, verify with rules + LLM."""
    from src.camp_validator import (
        classify_camp_page_tiered,
        should_auto_drop,
        should_skip_llm,
    )
    from src.platforms import _clean_name, _fetch, make_session
    from src.relevance import classify_session

    if not SETTINGS.get("b5_broad_discovery", True):
        return []

    max_candidates = int(SETTINGS.get("b5_discovery_max_candidates", 50))
    max_fetches = int(SETTINGS.get("b5_discovery_max_fetches", 25))
    existing = set(existing_register_urls or set())

    parsed = urlparse(seed_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    all_links = list(links)

    probe_cap = int(SETTINGS.get("b5_discovery_path_probes", 8))
    from src import session_log

    for path in _COMMON_SUMMER_PATHS[:probe_cap]:
        probe = f"{base}{path}"
        if normalize_url(probe) == normalize_url(seed_url):
            continue
        session_log.trace_probe(url=probe, label="discovery-path-probe")
        _, probe_links = await _fetch(probe, caller="discover:path-probe")
        all_links.extend(probe_links)

    candidates = collect_camp_candidate_links(seed_url, all_links)
    sessions: list[dict] = []
    fetches = 0

    for cand in candidates[:max_candidates]:
        cu = cand["url"]
        text = cand.get("text", "")
        if cu in existing:
            session_log.discovery_skip(url=cu, reason="already have this register URL")
            continue
        if should_auto_drop(cu)[0]:
            session_log.discovery_skip(url=cu, reason="auto-drop rules (junk host/path)")
            continue

        name = _clean_name(text, cu)
        score = score_camp_candidate(cu, text)
        keep_focus, focus_reason = classify_session(
            name,
            register_url=cu,
            platform="discovery",
        )
        session_log.trace(
            "discovery candidate",
            f"score={score} focus={keep_focus} ({focus_reason}) {cu}",
        )

        verified = False
        via = ""
        if score >= 4 and keep_focus:
            verified = True
            via = "high score + youth-summer"
        elif should_skip_llm(cu) and keep_focus:
            verified = True
            via = "rules (LLM skipped) + youth-summer"
        elif fetches < max_fetches:
            fetches += 1
            session_log.discovery_fetch(n=fetches, max_fetches=max_fetches, url=cu, link_text=text)
            page_text, _ = await _fetch(cu, caller="discover:verify")
            if not page_text.strip() and not keep_focus:
                session_log.discovery_verdict(url=cu, kept=False, reason="empty page, not youth-summer")
                continue
            if should_skip_llm(cu):
                verified = keep_focus or bool(_STRONG_CAMP_SIGNAL.search(page_text))
                via = "page rules (LLM skipped)"
                session_log.discovery_verdict(
                    url=cu,
                    kept=verified,
                    reason="rules only (LLM skipped)",
                    stage="rules",
                )
            else:
                try:
                    verified, reason, stage = classify_camp_page_tiered(
                        cu,
                        link_text=text,
                        town_hint=town_hint,
                        page_text=page_text,
                    )
                    via = f"LLM {stage}"
                    session_log.discovery_verdict(
                        url=cu,
                        kept=verified,
                        reason=reason,
                        stage=stage,
                    )
                    if verified and len(name) < 4:
                        name = _clean_name(page_text[:160], cu)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("discovery verify failed %s: %s", cu, exc)
                    session_log.discovery_verdict(url=cu, kept=False, reason=str(exc)[:120])
                    continue
        elif keep_focus and score >= 2:
            verified = True
            via = "medium score + youth-summer (no fetch budget left)"
        else:
            session_log.discovery_skip(
                url=cu,
                reason=f"not verified (score={score}, fetches={fetches}/{max_fetches})",
            )

        if not verified:
            continue

        session_log.discovery_keep(name=name, url=cu, via=via or "verified")
        sessions.append(
            make_session(
                name,
                cu,
                platform="discovery",
                source_url=seed_url,
            )
        )
        existing.add(cu)

    if candidates:
        session_log.discovery_done(found=len(sessions), fetches=fetches)
    return sessions
