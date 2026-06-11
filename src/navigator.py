"""Bounded recursive navigator for Phase B.5 provider enumeration.

Models each provider site as landing → catalog → detail → register, with
structured adapters as fast-path shortcuts through the same verification gate.
"""

from __future__ import annotations

import enum
import json
import logging
import re
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlparse

from config.prompts import NAVIGATOR_ROLE_CLASSIFIER_SYSTEM
from config.settings import SETTINGS
from src.enrollment_signals import attach_inline_verification, verify_registrable
from src.llm import OllamaError, chat_with_repair
from src.registration import (
    crawl_link_score,
    is_camp_catalog_url,
    is_registration_platform_url,
    registration_url_priority,
)
from src.urls import normalize_url

logger = logging.getLogger(__name__)

_DETAIL_PATH_RE = re.compile(
    r"/(our-programs|programs|camp|camps|summer|classes|activities)/[^/]+",
    re.I,
)
_YOUTH_CAMP_PAGE_RE = re.compile(
    r"summer\s+camp|day\s+camp|ages?\s+\d|grades?\s+[k0-9]|youth|kids?",
    re.I,
)
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.M)
# roadmap2 Phase 4 — anti-drift. Same-host links that are clearly NOT youth
# programs (research/medical/corporate/news) must not become catalog fan-out
# targets, so the crawl stops wandering into Mass General psychiatry pages etc.
_OFF_TOPIC_RE = re.compile(
    r"/(?:research|clinical|psychiatry|imaging|radiology|oncology|cardiac|"
    r"faculty|publications?|pubmed|patient|careers?|investor|press|newsroom|"
    r"privacy|terms|annual-report|board-of|leadership|giving|donate)\b",
    re.I,
)


class PageRole(enum.Enum):
    LANDING = "landing"
    CATALOG = "catalog"
    DETAIL = "detail"
    REGISTER = "register"


@dataclass
class NavNode:
    url: str
    role: PageRole
    depth: int
    parent_url: str = ""


def _wait_for(role: PageRole, url: str) -> str | None:
    from src.crawl import fetch_wait_until

    kind = "register" if role == PageRole.REGISTER else ""
    if role == PageRole.REGISTER:
        return fetch_wait_until(url, kind="register")
    if is_registration_platform_url(url):
        return fetch_wait_until(url, kind="portal")
    return fetch_wait_until(url, kind=kind) or None


def extract_camp_links(page_url: str, links: list[dict]) -> list[str]:
    """Same-host camp-ish links suitable for catalog fan-out."""
    seed_host = urlparse(page_url).netloc.lower().replace("www.", "")
    seen: set[str] = set()
    scored: list[tuple[int, str]] = []

    for link in links:
        u = normalize_url(link.get("url", ""))
        if not u or u in seen:
            continue
        text = (link.get("text") or "").strip()
        host = urlparse(u).netloc.lower().replace("www.", "")
        score = crawl_link_score(u, text)
        if score < 40:
            continue
        if host != seed_host and not is_registration_platform_url(u):
            continue
        # Anti-drift: skip same-host research/medical/corporate sections.
        if _OFF_TOPIC_RE.search(urlparse(u).path) and not is_registration_platform_url(u):
            continue
        if is_camp_catalog_url(u) and "program_details" not in u.lower():
            if "iteminfo" not in u.lower():
                continue
        if normalize_url(u) == normalize_url(page_url):
            continue
        seen.add(u)
        scored.append((score, u))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [u for _, u in scored]


def find_register_link(page_url: str, links: list[dict]) -> str:
    """Best registration/checkout link on a detail page.

    roadmap2 Phase 4: a register URL must stay on the provider's host or land on
    a recognized registration host (allow-list) — an off-host research/news link
    (e.g. ncbi.nlm.nih.gov) is never a camp checkout, no matter its link text.
    """
    from src.junk_audit import is_offhost_register

    best = ""
    best_score = 0
    for link in links:
        u = normalize_url(link.get("url", ""))
        if not u:
            continue
        if is_offhost_register(u, page_url):
            continue
        text = link.get("text") or ""
        combined = f"{u} {text}"
        score = 0
        if is_registration_platform_url(u):
            score = registration_url_priority(u) + 60
        else:
            score = crawl_link_score(u, text)
        if re.search(r"register|enroll|sign\s*up", combined, re.I):
            score += 25
        if score > best_score:
            best_score = score
            best = u
    return best if best_score >= 40 else ""


def _detail_page_signals(url: str, html: str, links: list[dict]) -> bool:
    if _DETAIL_PATH_RE.search(urlparse(url).path):
        return True
    if _YOUTH_CAMP_PAGE_RE.search(html) and len(extract_camp_links(url, links)) < 3:
        return True
    return False


def _classify_role_rules(
    url: str,
    html: str,
    links: list[dict],
) -> PageRole | None:
    if is_camp_catalog_url(url):
        return PageRole.CATALOG

    low = url.lower()
    if is_registration_platform_url(url):
        if "iteminfo" in low or "program_details" in low:
            return PageRole.REGISTER
        sig = verify_registrable(url, html)
        if sig.has_cart_cta or sig.auto_verdict == "parent_ready":
            return PageRole.REGISTER
        return PageRole.REGISTER

    camp_links = extract_camp_links(url, links)
    if len(camp_links) >= 3:
        return PageRole.CATALOG

    if _detail_page_signals(url, html, links):
        return PageRole.DETAIL

    if camp_links and len(camp_links) < 3 and _YOUTH_CAMP_PAGE_RE.search(html):
        return PageRole.DETAIL

    return None


def classify_role(
    url: str,
    html: str,
    links: list[dict],
    *,
    hinted_role: PageRole | None = None,
) -> PageRole:
    """Rules first; LLM only when rules are inconclusive."""
    if hinted_role and hinted_role != PageRole.LANDING:
        ruled = _classify_role_rules(url, html, links)
        if ruled is None or ruled == hinted_role:
            return hinted_role

    ruled = _classify_role_rules(url, html, links)
    if ruled is not None:
        return ruled

    return _classify_role_llm(url, html, links, fallback=hinted_role or PageRole.LANDING)


def _classify_role_llm(
    url: str,
    html: str,
    links: list[dict],
    *,
    fallback: PageRole,
) -> PageRole:
    from src.camp_validator import _truncate

    sample_links = [
        {"url": l.get("url", ""), "text": (l.get("text") or "")[:80]}
        for l in links[:40]
    ]
    user = json.dumps(
        {
            "url": url,
            "page_text": _truncate(html, SETTINGS.get("ollama_session_max_chars", 6000)),
            "links": sample_links,
        },
        ensure_ascii=False,
    )
    # Navigation/extraction routes to the larger instruct model with JSON-repair + retry.
    model = SETTINGS.get("ollama_verify_model") or SETTINGS.get("ollama_model")
    try:
        resp = chat_with_repair(
            NAVIGATOR_ROLE_CLASSIFIER_SYSTEM,
            user,
            model=model,
            temperature=0.0,
            timeout=int(SETTINGS.get("b5_agent_nav_timeout_s", 90)),
            num_predict=256,
            purpose="navigator_role",
        )
        role_str = str(resp.get("role", "")).lower().strip()
        for role in PageRole:
            if role.value == role_str:
                return role
    except OllamaError as exc:
        logger.warning("navigator role LLM failed for %s: %s", url, exc)
    return fallback


def _extract_name_from_page(url: str, html: str, links: list[dict]) -> tuple[str, str]:
    """Return (name, name_source). Source is provenance for the validation gate:
    "title" (page H1), "link_text" (self-link anchor), or "slug" (URL tail)."""
    m = _TITLE_RE.search(html)
    if m:
        return m.group(1).strip(), "title"
    for link in links:
        if normalize_url(link.get("url", "")) == normalize_url(url):
            text = (link.get("text") or "").strip()
            if text and len(text) > 2:
                return text, "link_text"
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    name = slug.replace("-", " ").replace("_", " ").title() if slug else "Camp program"
    return name, "slug"


async def extract_one_camp(
    url: str,
    html: str,
    links: list[dict],
    *,
    town_hint: str = "",
) -> dict:
    """Build a session dict from a detail page (rules first, LLM if thin)."""
    from src.platforms import make_session

    name, name_source = _extract_name_from_page(url, html, links)
    reg = find_register_link(url, links)
    ages = ""
    dates = ""
    m_age = re.search(r"ages?\s*:?\s*[\d\-–kK]+", html, re.I)
    if m_age:
        ages = m_age.group(0).strip()
    m_date = re.search(
        r"(?:June|July|August)[a-z]*\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?",
        html,
        re.I,
    )
    if m_date:
        dates = m_date.group(0).strip()

    # roadmap2 Phase 4: only ask the LLM to extract from a *substantive* page.
    # The old code did the opposite — it ran extraction precisely when the page
    # was thin (<200 chars), which fabricated camps from login/empty shells.
    from src.camp_validator import should_llm_extract

    extract_status = ""
    ok, why = should_llm_extract(html)
    if not reg and ok:
        from src.camp_validator import extract_camp_sessions

        raw = extract_camp_sessions(
            url, page_text=html, page_links=links, town_hint=town_hint
        )
        if raw:
            c = raw[0]
            if c.get("name"):
                name = c["name"]
                name_source = "llm"
            ages = c.get("ages") or ages
            dates = c.get("dates") or dates
            regs = c.get("register_urls") or []
            if regs:
                reg = regs[0]
    elif not reg and not ok:
        # Thin/login/empty page — do not fabricate; mark for a render pass.
        extract_status = why

    session = make_session(
        name,
        reg or "",
        info_url=url,
        ages=ages,
        dates=dates,
        platform="navigator",
        source_url=url,
        kind="session" if reg else "portal",
        name_source=name_source,
    )
    if extract_status:
        session["extract_status"] = extract_status
        session["parent_verdict"] = extract_status
    return session


def _dedupe_sessions(sessions: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for s in sessions:
        key = normalize_url(s.get("register_url") or s.get("info_url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


async def _verify_session(
    session: dict,
    fetched_url: str,
    html: str,
) -> dict:
    from src import session_log
    from src.enrollment_signals import can_verify_inline
    from src.verdict_policy import apply_verdict_policy

    row = {**session, "platform": session.get("platform") or "navigator"}
    if can_verify_inline(row, fetched_url) and html.strip():
        row = attach_inline_verification(row, fetched_url, html)
        session_log.nav_verified(
            url=fetched_url,
            verdict=row.get("parent_verdict", ""),
            name=row.get("name", ""),
        )
    # roadmap2 Phase 6: deterministic per-platform verdict policy (MyRec needs_js).
    return apply_verdict_policy(row)


async def _finish_adapter_sessions(
    adapter_sessions: list[dict],
    *,
    html_by_url: dict[str, str],
    fetch_page,
) -> list[dict]:
    finished: list[dict] = []
    for s in adapter_sessions:
        reg = normalize_url(s.get("register_url") or "")
        info = s.get("info_url") or reg
        row = {**s}
        if info and not row.get("info_url"):
            row["info_url"] = info
        if not reg:
            finished.append(row)
            continue
        html = html_by_url.get(reg, "")
        if not html.strip():
            html, _ = await fetch_page(reg, kind="register")
            html_by_url[reg] = html
        finished.append(await _verify_session(row, reg, html))
    return finished


async def navigate_provider(
    seed_url: str,
    *,
    town_hint: str = "",
    max_depth: int | None = None,
    max_fetches: int | None = None,
) -> list[dict]:
    """Bounded BFS traversal: catalog fan-out, detail → register, inline verify."""
    from src import session_log
    from src.crawl import fetch_wait_until
    from src.platforms import (
        _ADAPTERS,
        _fetch,
        _run_adapter,
        adapter_veracross,
        detect_platform,
        make_session,
    )

    depth_cap = int(max_depth if max_depth is not None else SETTINGS.get("b5_nav_max_depth", 3))
    fetch_cap = int(
        max_fetches if max_fetches is not None else SETTINGS.get("b5_nav_max_fetches", 25)
    )

    session_log.nav_start(seed_url=seed_url, max_depth=depth_cap, max_fetches=fetch_cap)

    queue: deque[NavNode] = deque([NavNode(seed_url, PageRole.LANDING, 0)])
    seen: set[str] = set()
    html_by_url: dict[str, str] = {}
    sessions: list[dict] = []
    pending: dict[str, dict] = {}
    fetches = 0

    async def fetch_page(url: str, *, kind: str = "") -> tuple[str, list[dict]]:
        nonlocal fetches
        if fetches >= fetch_cap:
            return "", []
        wait = fetch_wait_until(url, kind=kind) if kind else _wait_for(PageRole.LANDING, url)
        session_log.nav_fetch(role=kind or "page", url=url)
        text, links = await _fetch(
            url,
            caller=f"navigator:{kind or 'page'}",
            wait_until=wait,
            kind=kind,
        )
        fetches += 1
        html_by_url[normalize_url(url)] = text
        if town_hint and text.strip():
            from src.capture import capture_page

            capture_page(town_hint, url, text)
        return text, links

    while queue and fetches < fetch_cap:
        node = queue.popleft()
        u = normalize_url(node.url)
        if not u or u in seen or node.depth > depth_cap:
            continue
        seen.add(u)

        kind = ""
        if node.role == PageRole.REGISTER:
            kind = "register"
        elif is_registration_platform_url(u):
            kind = "portal"

        try:
            text, links = await fetch_page(u, kind=kind)
        except Exception as exc:  # noqa: BLE001
            logger.warning("navigator fetch failed %s: %s", u, exc)
            session_log.nav_fetch_error(url=u, error=str(exc))
            continue

        plat = detect_platform(u, links, text)
        if plat in _ADAPTERS and node.role in (PageRole.LANDING, PageRole.CATALOG):
            session_log.trace_adapter(platform=plat, url=u)
            try:
                adapter_sessions = await _run_adapter(plat, u, links, text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("navigator adapter %s failed for %s: %s", plat, u, exc)
                adapter_sessions = []
            if adapter_sessions:
                finished = await _finish_adapter_sessions(
                    adapter_sessions,
                    html_by_url=html_by_url,
                    fetch_page=fetch_page,
                )
                sessions.extend(finished)
                session_log.nav_adapter_done(platform=plat, count=len(finished))
                continue

        role = classify_role(u, text, links, hinted_role=node.role)
        session_log.nav_role(url=u, role=role.value, depth=node.depth)

        if role == PageRole.CATALOG:
            camp_links = extract_camp_links(u, links)
            session_log.nav_fanout(catalog_url=u, detail_count=len(camp_links))
            for camp_url in camp_links:
                nu = normalize_url(camp_url)
                if nu and nu not in seen and node.depth + 1 <= depth_cap:
                    queue.append(
                        NavNode(camp_url, PageRole.DETAIL, node.depth + 1, parent_url=u)
                    )
            if not camp_links and fetches < fetch_cap:
                from src.platforms import adapter_llm

                try:
                    llm_sessions = await adapter_llm(u, links, text, town_hint=town_hint)
                    finished = await _finish_adapter_sessions(
                        llm_sessions,
                        html_by_url=html_by_url,
                        fetch_page=fetch_page,
                    )
                    sessions.extend(finished)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("navigator catalog LLM extract failed %s: %s", u, exc)

        elif role == PageRole.DETAIL:
            rec = await extract_one_camp(u, text, links, town_hint=town_hint)
            rec["info_url"] = u
            reg = find_register_link(u, links)
            if reg and normalize_url(reg) not in seen and node.depth + 1 <= depth_cap:
                pending[u] = rec
                queue.append(NavNode(reg, PageRole.REGISTER, node.depth + 1, parent_url=u))
            else:
                if reg:
                    rec["register_url"] = reg
                sessions.append(rec)

        elif role == PageRole.REGISTER:
            if node.parent_url and node.parent_url in pending:
                rec = pending.pop(node.parent_url)
                rec["register_url"] = u
                sessions.append(await _verify_session(rec, u, text))
            elif is_registration_platform_url(u):
                portal_name, portal_src = _extract_name_from_page(u, text, links)
                portal = make_session(
                    portal_name,
                    u,
                    info_url=node.parent_url or "",
                    platform=plat or "navigator",
                    source_url=seed_url,
                    kind="portal",
                    name_source=portal_src,
                )
                sessions.append(await _verify_session(portal, u, text))
            else:
                sig = verify_registrable(u, text)
                reg_name, reg_src = _extract_name_from_page(u, text, links)
                rec = make_session(
                    reg_name,
                    u,
                    info_url=node.parent_url or "",
                    platform="navigator",
                    source_url=seed_url,
                    name_source=reg_src,
                )
                if sig.auto_verdict:
                    rec = attach_inline_verification(rec, u, text)
                sessions.append(rec)

        elif role == PageRole.LANDING and node.depth == 0:
            camp_links = extract_camp_links(u, links)
            if camp_links:
                for camp_url in camp_links[:10]:
                    nu = normalize_url(camp_url)
                    if nu and nu not in seen:
                        queue.append(
                            NavNode(camp_url, PageRole.DETAIL, node.depth + 1, parent_url=u)
                        )
            elif plat in ("custom", ""):
                if any("veracross.com" in l.get("url", "").lower() for l in links):
                    vc = await adapter_veracross(u, links, text)
                    if vc:
                        finished = await _finish_adapter_sessions(
                            vc,
                            html_by_url=html_by_url,
                            fetch_page=fetch_page,
                        )
                        sessions.extend(finished)

    # Flush pending detail rows that never reached a register page
    for rec in pending.values():
        sessions.append(rec)

    result = _dedupe_sessions(sessions)
    session_log.nav_done(session_count=len(result), fetches=fetches)
    return result
