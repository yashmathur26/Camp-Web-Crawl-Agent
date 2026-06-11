"""roadmap2 Phase 2 — structured extraction from embedded schema.org JSON-LD.

JS/portal camp sites (Sawyer, active.com, many WordPress event plugins) emit
their real program data as `<script type="application/ld+json">` Event/Course
objects even when the visible DOM is button chrome. Reading that payload turns
"See Details" / "Back to Top" into real titles + dates + prices.

This module is pure (no network): give it rendered HTML, get back a list of
normalized program dicts. The crawl layer surfaces these into the page text so
downstream extraction sees real data instead of chrome.
"""

from __future__ import annotations

import json
import re

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)

# schema.org @types that represent a registrable program/session.
_EVENT_TYPES = {
    "event",
    "eventseries",
    "course",
    "courseinstance",
    "educationevent",
    "businessevent",
    "childrensevent",
    "socialevent",
    "camp",
}


def _iter_nodes(data):
    """Yield every dict node from a parsed JSON-LD payload (dict / list / @graph)."""
    if isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                yield from _iter_nodes(node)
        yield data
    elif isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)


def _types_of(node: dict) -> set[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return {t.lower()}
    if isinstance(t, list):
        return {str(x).lower() for x in t}
    return set()


def _fmt_date(node: dict) -> str:
    start = str(node.get("startDate") or "").strip()
    end = str(node.get("endDate") or "").strip()
    start = start.split("T")[0] if start else ""
    end = end.split("T")[0] if end else ""
    if start and end and end != start:
        return f"{start} – {end}"
    return start or end


def _price(node: dict) -> str:
    offers = node.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict):
        price = offers.get("price") or offers.get("lowPrice")
        if price not in (None, ""):
            cur = offers.get("priceCurrency", "")
            sym = "$" if cur in ("", "USD") else f"{cur} "
            return f"{sym}{price}"
    return ""


def _register_url(node: dict) -> str:
    offers = node.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if isinstance(offers, dict) and offers.get("url"):
        return str(offers["url"])
    return str(node.get("url") or "")


def extract_jsonld_events(html: str) -> list[dict]:
    """Parse embedded JSON-LD and return normalized program dicts.

    Each dict: {name, dates, price, register_url}. Only nodes with an event-ish
    @type and a non-empty name are returned. De-duplicated on (name, dates).
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in _JSONLD_RE.finditer(html or ""):
        blob = m.group(1).strip()
        try:
            data = json.loads(blob)
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _iter_nodes(data):
            if not isinstance(node, dict):
                continue
            if not (_types_of(node) & _EVENT_TYPES):
                continue
            name = str(node.get("name") or "").strip()
            if not name:
                continue
            dates = _fmt_date(node)
            key = (name.lower(), dates)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "name": name,
                    "dates": dates,
                    "price": _price(node),
                    "register_url": _register_url(node),
                }
            )
    return out


def structured_summary(events: list[dict]) -> str:
    """Render events as a compact text block to prepend to a page's text, so the
    downstream name/date/price extraction sees real program data."""
    if not events:
        return ""
    lines = ["## STRUCTURED PROGRAMS (embedded schema.org data)"]
    for e in events:
        meta = " | ".join(x for x in (e.get("dates"), e.get("price")) if x)
        lines.append(f"- {e['name']}" + (f" | {meta}" if meta else ""))
    return "\n".join(lines)
