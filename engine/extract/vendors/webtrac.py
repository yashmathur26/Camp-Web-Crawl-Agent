"""WebTrac/myvscloud extractor — PORTED from src/platforms.py::adapter_webtrac
(task 3.2) with Program grouping per plan §2.

Source of truth: the server-rendered camp catalog
  https://{org}.myvscloud.com/webtrac/web/search.html?module=AR&type=CAMP
plus any camp-category catalogs linked from the seed. Each item (FMID) is one
session; iteminfo pages are content-rich and serve as info_urls. Camp-scoped
catalog → R4.2: catalog scope IS the evidence.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from engine.extract.base import ExtractResult, Extractor, group_sessions_into_programs
from engine.fetch.client import Budget, BudgetExceeded, FetchClient
from engine.fetch.urls import normalize_url
from engine.model import Gap, Program, Provider, Session

_BAD_NAME_RE = re.compile(
    r"^(item details|add to (cart|selection|wishlist)|share|more info|"
    r"enrollment count details)",
    re.I,
)
_DATE_ONLY_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}")
_DATE_RANGE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}\s*[-–]\s*\d{1,2}/\d{1,2}/\d{2,4}")


def parse_catalog_links(links: list[dict]) -> list[dict]:
    """One row per FMID from a WebTrac catalog page's links (ported)."""
    by_id: dict[str, dict] = {}
    for link in links:
        url = link.get("url", "")
        text = (link.get("text") or "").strip()
        parsed = urlparse(url)
        if "iteminfo" not in parsed.path.lower():
            continue
        qs = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
        fmid = (qs.get("fmid") or [""])[0]
        if not fmid:
            continue
        entry = by_id.setdefault(
            fmid, {"name": "", "dates": "", "register_url": "", "id": fmid}
        )
        low = url.lower()
        if not any(x in low for x in ("option=", "mode=", "interfaceparameter")):
            if text and not _DATE_ONLY_RE.match(text) and not _BAD_NAME_RE.match(text):
                entry["name"] = entry["name"] or text
            entry["register_url"] = entry["register_url"] or normalize_url(url)
        if _DATE_RANGE_RE.search(text) or _DATE_ONLY_RE.match(text):
            entry["dates"] = entry["dates"] or text.replace(" -", " - ")
    return [e for e in by_id.values() if e["register_url"] and e["name"]]


def catalog_urls_for(provider: Provider, seed_links: list[dict]) -> list[str]:
    urls: list[str] = []
    if provider.org_id:
        urls.append(
            f"https://{provider.org_id}.myvscloud.com/webtrac/web/search.html"
            f"?module=AR&type=CAMP"
        )
    for link in seed_links:
        u = link.get("url", "")
        low = u.lower()
        if "myvscloud.com" not in low and "webtrac" not in low:
            continue
        if "search.html" in low and (
            "type=camp" in low.replace(" ", "")
            or ("category=" in low and "camp" in low)
        ):
            urls.append(u)
    return list(dict.fromkeys(urls))


class WebtracExtractor(Extractor):
    vendor = "webtrac"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        from engine.fetch.render import fetch_rendered

        budget = Budget()
        _seed_text, seed_links, _ = fetch.fetch_text(provider.seed_url, budget=budget)
        catalogs = catalog_urls_for(provider, seed_links)
        if not catalogs:
            return ExtractResult(
                gap=Gap(
                    provider_id=provider.provider_id, reason="needs_review",
                    evidence=f"no WebTrac catalog URL derivable from seed {provider.seed_url}",
                    suggested_action="set org_id in the registry",
                ),
                fetch_log=fetch.log,
            )

        rows: dict[str, dict] = {}
        catalog_texts: dict[str, str] = {}
        for cat in catalogs[:5]:
            # myvscloud 403s non-browser clients (Cloudflare) — plain first,
            # rendered fallback (R5.7: browser as last resort, found necessary
            # in the Phase-3 live run).
            text, cat_links, _ = fetch.fetch_text(cat, budget=budget)
            if not any("iteminfo" in l.get("url", "").lower() for l in cat_links):
                budget.check()
                text, cat_links, _ = await fetch_rendered(cat, cache=fetch.cache, log=fetch.log)
            catalog_texts[cat] = text
            for r in parse_catalog_links(cat_links):
                if "module=ar" not in r["register_url"].lower():
                    continue
                rows.setdefault(r["id"], {**r, "catalog": cat})

        if not rows:
            return ExtractResult(
                gap=Gap(
                    provider_id=provider.provider_id, reason="empty",
                    evidence=f"camp catalog(s) {catalogs[:2]} yielded no item rows",
                    suggested_action="check catalog URL / season availability",
                ),
                fetch_log=fetch.log,
            )

        # iteminfo pages are the preferred info_urls (content-rich per plan §6);
        # rendered within budget — leftover sessions fall back to their catalog
        # page (also rendered this run, carries every name + dates).
        sessions: list[Session] = []
        for r in rows.values():
            info_url = r["register_url"]
            try:
                budget.check()
                text, _l, _ = await fetch_rendered(info_url, cache=fetch.cache, log=fetch.log)
                if len(text) < 400:
                    info_url = r["catalog"]
            except BudgetExceeded:
                info_url = r["catalog"]
            sessions.append(
                Session(
                    name=r["name"], info_url=info_url,
                    register_url=r["register_url"], dates=r.get("dates", ""),
                    extractor=self.vendor,
                )
            )

        programs = group_sessions_into_programs(provider, sessions, camp_scoped=True)
        return ExtractResult(programs=programs, fetch_log=fetch.log)
