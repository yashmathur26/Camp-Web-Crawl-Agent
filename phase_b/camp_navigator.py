"""Agent-style navigation: survey all links on a page, reason, fetch only the best few."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from config.prompts import CAMP_NAVIGATOR_SYSTEM
from config.settings import SETTINGS
from phase_b.enrollment_signals import attach_inline_verification, can_verify_inline
from shared.llm import OllamaError, chat_with_repair
from phase_b.registration import crawl_link_score, is_registration_platform_url
from shared.urls import normalize_url

logger = logging.getLogger(__name__)

# Cross-host links that look like an enroll destination (external Jotform/Google
# Form/custom SaaS register pages). Used to keep them in the ranked set instead
# of dropping them as off-host noise.
_REGISTER_INTENT_RE = re.compile(
    r"register|registration|enroll|sign[\s\-]?up|signup|/forms?/|jotform|"
    r"formstack|wufoo|regfox|application|apply",
    re.I,
)


def _rank_links_for_agent(seed_url: str, links: list[dict], cap: int) -> list[dict]:
    """Dedupe and rank links; return top N for the navigator prompt."""
    seed_host = urlparse(seed_url).netloc.lower().replace("www.", "")
    seen: set[str] = set()
    scored: list[tuple[int, dict]] = []

    for link in links:
        u = normalize_url(link.get("url", ""))
        if not u or u in seen:
            continue
        text = (link.get("text") or "").strip()
        host = urlparse(u).netloc.lower().replace("www.", "")
        score = crawl_link_score(u, text)
        if score < 0:
            continue
        # P4.1: stop dropping every cross-host non-platform link. An external
        # register target (Jotform/Google Form/custom SaaS) is exactly what we
        # want to keep — down-weight it so the model still sees it. Generic
        # off-host links (social, partners) still get pruned so they don't crowd
        # the prompt.
        if host != seed_host and not is_registration_platform_url(u):
            if _REGISTER_INTENT_RE.search(f"{u} {text}"):
                score = max(score - 15, 5)
            else:
                score -= 30
                if score < 0:
                    continue
        seen.add(u)
        scored.append((score, {"url": u, "text": text}))

    scored.sort(key=lambda x: (-x[0], x[1]["url"]))
    return [item for _, item in scored[:cap]]


def _pick_agent_urls(
    seed_url: str,
    page_text: str,
    links: list[dict],
    *,
    town_hint: str = "",
) -> dict:
    from shared import session_log
    from phase_b.camp_validator import _truncate

    cap = int(SETTINGS.get("b5_agent_nav_link_cap", 60))
    ranked = _rank_links_for_agent(seed_url, links, cap)
    numbered = [
        {"n": i + 1, "url": lk["url"], "text": lk.get("text", "")[:120]}
        for i, lk in enumerate(ranked)
    ]

    session_log.agent_nav_start(seed_url=seed_url, link_count=len(numbered))
    for item in numbered:
        session_log.agent_nav_link_option(
            n=item["n"], url=item["url"], text=item["text"]
        )

    user = json.dumps(
        {
            "seed_url": seed_url,
            "town_hint": town_hint,
            "page_text": _truncate(page_text, SETTINGS.get("ollama_session_max_chars", 6000)),
            "links": numbered,
        },
        ensure_ascii=False,
    )
    # Navigation routes to the larger instruct model with JSON-repair + retry.
    model = SETTINGS.get("ollama_verify_model") or SETTINGS.get("ollama_model")
    try:
        resp = chat_with_repair(
            CAMP_NAVIGATOR_SYSTEM,
            user,
            model=model,
            temperature=0.0,
            timeout=int(SETTINGS.get("b5_agent_nav_timeout_s", 90)),
            num_predict=1024,
            purpose="camp_navigator",
        )
    except OllamaError as exc:
        logger.warning("agent navigator failed for %s: %s", seed_url, exc)
        session_log.agent_nav_failed(error=str(exc))
        return {"catalog_urls": [], "register_urls": [], "reasoning": ""}

    reasoning = str(resp.get("reasoning", ""))
    session_log.agent_nav_reasoning(reasoning=reasoning)

    catalog: list[dict] = []
    register: list[dict] = []
    for key, dest in (("catalog_urls", catalog), ("register_urls", register)):
        raw = resp.get(key)
        if not isinstance(raw, list):
            continue
        for entry in raw[:3 if key == "catalog_urls" else 2]:
            if isinstance(entry, str):
                u = normalize_url(entry)
                if u:
                    dest.append({"url": u, "label": "", "why": ""})
            elif isinstance(entry, dict):
                u = normalize_url(str(entry.get("url", "")))
                if u:
                    dest.append(
                        {
                            "url": u,
                            "label": str(entry.get("label", ""))[:120],
                            "why": str(entry.get("why", ""))[:200],
                        }
                    )

    for pick in catalog:
        session_log.agent_nav_pick(
            kind="catalog", url=pick["url"], label=pick["label"], why=pick["why"]
        )
    for pick in register:
        session_log.agent_nav_pick(
            kind="register", url=pick["url"], label=pick["label"], why=pick["why"]
        )

    return {"catalog_urls": catalog, "register_urls": register, "reasoning": reasoning}


async def agent_navigate_provider(
    seed_url: str,
    page_text: str,
    links: list[dict],
    *,
    town_hint: str = "",
) -> tuple[list[dict], dict]:
    """Survey seed-page links with one LLM call; fetch only chosen catalog/register URLs."""
    from shared import session_log
    from phase_b.platforms import (
        _ADAPTERS,
        _fetch,
        _run_adapter,
        adapter_llm,
        adapter_veracross,
        detect_platform,
        make_session,
    )

    picks = _pick_agent_urls(seed_url, page_text, links, town_hint=town_hint)
    sessions: list[dict] = []
    # P4.4: track fetched URLs and emitted register URLs separately. Previously a
    # single `seen_regs` set conflated "catalog page I already fetched" with
    # "register URL I already emitted", so a catalog URL was skipped (or fetched
    # twice) based on the register set. Keep them apart.
    fetched_urls: set[str] = set()
    seen_regs: set[str] = set()

    max_catalog = int(SETTINGS.get("b5_agent_nav_max_catalog_fetches", 3))
    max_register = int(SETTINGS.get("b5_agent_nav_max_register_fetches", 2))

    def _maybe_verify(session: dict, fetched_url: str, html: str) -> dict:
        row = {**session, "platform": session.get("platform") or "agent_nav"}
        if can_verify_inline(row, fetched_url):
            row = attach_inline_verification(row, fetched_url, html)
            session_log.agent_nav_verified(
                url=fetched_url,
                verdict=row.get("parent_verdict", ""),
                name=row.get("name", ""),
            )
        return row

    async def _enumerate_url(target: str, *, kind: str) -> tuple[list[dict], str]:
        session_log.agent_nav_fetch(kind=kind, url=target)
        text, page_links = await _fetch(
            target, caller=f"agent_nav:{kind}", kind=kind
        )
        plat = detect_platform(target, page_links, text)
        found: list[dict] = []
        if plat in _ADAPTERS:
            session_log.trace_adapter(platform=plat, url=target)
            found = await _run_adapter(plat, target, page_links, text)
        if not found and any("veracross.com" in l.get("url", "").lower() for l in page_links):
            found = await adapter_veracross(target, page_links, text)
        if not found:
            found = await adapter_llm(target, page_links, text, town_hint=town_hint)
        return found, text

    for pick in picks.get("catalog_urls", [])[:max_catalog]:
        u = pick["url"]
        if u in fetched_urls:
            continue
        fetched_urls.add(u)
        try:
            found, html = await _enumerate_url(u, kind="catalog")
            for s in found:
                reg = s.get("register_url", "")
                if reg and reg not in seen_regs:
                    seen_regs.add(reg)
                    sessions.append(_maybe_verify(s, u, html))
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent catalog fetch failed %s: %s", u, exc)
            session_log.agent_nav_fetch_error(url=u, error=str(exc))

    for pick in picks.get("register_urls", [])[:max_register]:
        u = pick["url"]
        if u in fetched_urls or u in seen_regs:
            continue
        fetched_urls.add(u)
        try:
            found, html = await _enumerate_url(u, kind="register")
            added = False
            for s in found:
                reg = s.get("register_url", "")
                if reg and reg not in seen_regs:
                    seen_regs.add(reg)
                    sessions.append(_maybe_verify(s, u, html))
                    added = True
            if not added and is_registration_platform_url(u):
                portal = make_session(
                    pick.get("label") or "Camp registration",
                    u,
                    platform="agent_nav",
                    source_url=seed_url,
                    kind="portal",
                )
                sessions.append(_maybe_verify(portal, u, html))
                seen_regs.add(u)
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent register fetch failed %s: %s", u, exc)
            session_log.agent_nav_fetch_error(url=u, error=str(exc))

    session_log.agent_nav_done(session_count=len(sessions))
    return sessions, picks
