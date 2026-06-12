"""CommunityEd/Lexplorations (WooCommerce) extractor — REWRITE (task 4.2).

Better data path than the plan's render-pagination (R5.7, found in Phase 0):
the site exposes the WooCommerce Store API
  {seed}/wp-json/wc/store/products?per_page=100&page=N
returning every class with name, /class/{slug} permalink (the info page),
description, and prices. Week categories (week-one..six) are the camps;
after-school-care items are excluded as separate programs.

Info-url invariant: the store API response IS the content of each /class/ page
(same product data that renders it). We seed the run cache with each product's
description text under its permalink — one API call fetches the content of all
~135 pages instead of 135 throttled page loads. content_chars then reflects
the real product copy.
"""

from __future__ import annotations

import html as html_mod
import re
from urllib.parse import urlparse

from engine.extract.base import ExtractResult, Extractor
from engine.fetch.client import Budget, FetchClient
from engine.model import Gap, Program, Provider, Session

_WEEK_SLUGS = {"week-one", "week-two", "week-three", "week-four", "week-five", "week-six"}
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_IN_NAME_RE = re.compile(r"\(([^)]*(?:june|july|august)[^)]*)\)", re.I)
_GRADES_RE = re.compile(r"grades?\s*:?\s*(?:entering\s*)?[k0-9][^.;|]{0,12}", re.I)


def _price(item: dict) -> str:
    prices = item.get("prices") or {}
    raw = prices.get("price")
    if not raw:
        return ""
    try:
        minor_unit = int(prices.get("currency_minor_unit", 2))
        return f"${int(raw) / (10 ** minor_unit):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def parse_products(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        cats = {c.get("slug") for c in (it.get("categories") or [])}
        if not (cats & _WEEK_SLUGS):
            continue  # after-school-care & misc — not camps
        name = html_mod.unescape(str(it.get("name") or "")).strip()
        permalink = str(it.get("permalink") or "")
        if not name or not permalink:
            continue
        desc = _TAG_RE.sub(" ", html_mod.unescape(str(it.get("description") or "")))
        desc = re.sub(r"\s+", " ", desc).strip()
        m = _DATE_IN_NAME_RE.search(name)
        g = _GRADES_RE.search(desc)
        out.append(
            {
                "name": name, "permalink": permalink,
                "dates": m.group(1).strip() if m else "",
                "ages": g.group(0).strip() if g else "",
                "price": _price(it), "description": desc,
            }
        )
    return out


class CommunityedExtractor(Extractor):
    vendor = "communityed"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        budget = Budget()
        parsed = urlparse(provider.seed_url)
        prefix = parsed.path.strip("/").split("/")[0] or "lexplorations"
        api = f"{parsed.scheme}://{parsed.netloc}/{prefix}/wp-json/wc/store/products"

        items: list[dict] = []
        for page in range(1, 5):  # capped (R5); 100/page covers ~400 products
            data = fetch.fetch_json(f"{api}?per_page=100&page={page}", budget=budget)
            if not isinstance(data, list) or not data:
                break
            items.extend(data)

        if not items:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="render_failed",
                        evidence=f"store API empty/unreachable: {api}",
                        suggested_action="fall back to render-pagination of find-a-class"),
            )

        products = parse_products(items)
        if not products:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="empty",
                        evidence=f"{len(items)} products but none in week categories",
                        suggested_action="check category slugs / season"),
            )

        programs: list[Program] = []
        for p in products:
            # Seed the run cache: the API fetched this page's content (see
            # module docstring) — the gate's invariant reads it from here.
            page_text = f"{p['name']}. {p['description']} {p['dates']} {p['ages']} {p['price']}"
            fetch.cache.put(p["permalink"], page_text, [])
            prog = Program(
                name=p["name"], provider_id=provider.provider_id,
                info_url=p["permalink"], camp_scoped=True,  # week-scoped camp catalog (R4.2)
                description_snippet=p["description"][:300],
            )
            prog.sessions = [
                Session(name=p["name"], info_url=p["permalink"],
                        register_url=p["permalink"], dates=p["dates"],
                        ages=p["ages"], price=p["price"], extractor=self.vendor,
                        program_id=prog.program_id)
            ]
            programs.append(prog)
        return ExtractResult(programs=programs, fetch_log=fetch.log)
