"""Viking Sports adapter (operator request, round 3). vikingcamps.com is a
multi-town franchise whose program search is SERVER-RENDERED WordPress with a
clean taxonomy: /programs/program-type/summer-camp/ (+ /page/N/) lists every
summer camp week; /program/{slug}/ are detail pages. Camp-scoped catalog (R4.2).
Rows for other franchise towns are filtered to the provider's town when any
town-tagged rows exist. Fixture: tests/fixtures/viking/summer_camp_catalog.html.
"""

from __future__ import annotations

import re
from html import unescape

from engine.extract.base import ExtractResult, Extractor, group_sessions_into_programs
from engine.fetch.client import Budget, FetchClient
from engine.model import Gap, Provider, Session

CATALOG = "https://www.vikingcamps.com/programs/program-type/summer-camp/"
_SEG_RE = re.compile(r'href="(https://www\.vikingcamps\.com/program/[^"]+)"[^>]*>([\s\S]*?)</a>')
_TAG_RE = re.compile(r"<[^>]+>")
_DATES_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s*[-–]\s*"
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+)?\d{1,2}"
)
_AGES_RE = re.compile(r"Ages?\s+\d{1,2}(?:\s*[-–]\s*\d{1,2})?(?:\s+Only)?", re.I)
_FEE_RE = re.compile(r"\$\d{2,4}")


def parse_catalog(html: str, town: str = "") -> list[dict]:
    """One row per /program/ link; evidence parsed from the card segment that
    FOLLOWS the link (dates/ages/fee/location sit after the title)."""
    matches = list(_SEG_RE.finditer(html or ""))
    rows: list[dict] = []
    seen: set[str] = set()
    for i, m in enumerate(matches):
        url, raw_name = m.group(1), m.group(2)
        name = re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", raw_name))).strip()
        if not name or len(name) < 8 or url in seen:
            continue
        seen.add(url)
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else min(len(html), m.end() + 3000)
        segment = unescape(_TAG_RE.sub(" ", html[m.end():seg_end]))
        dm, am, fm = _DATES_RE.search(segment), _AGES_RE.search(segment), _FEE_RE.search(segment)
        rows.append({
            "name": name, "detail_url": url,
            "dates": dm.group(0) if dm else "",
            "ages": am.group(0) if am else "",
            "price": fm.group(0) if fm else "",
            "in_town": bool(town) and town.lower() in segment.lower() + name.lower(),
        })
    if any(r["in_town"] for r in rows):
        rows = [r for r in rows if r["in_town"]]
    return rows


class VikingExtractor(Extractor):
    vendor = "viking"

    async def extract(self, provider: Provider, fetch: FetchClient) -> ExtractResult:
        budget = Budget()
        rows: list[dict] = []
        for page in range(1, 9):  # capped; "115 programs" ≈ 6 pages of 20
            url = CATALOG if page == 1 else f"{CATALOG}page/{page}/"
            _t, _l, html = fetch.fetch_text(url, budget=budget)
            page_rows = parse_catalog(html, town=provider.town)
            if not page_rows:
                break
            rows.extend(page_rows)
        if not rows:
            return ExtractResult(
                gap=Gap(provider_id=provider.provider_id, reason="empty",
                        evidence=f"no program rows on {CATALOG}",
                        suggested_action="check catalog URL / season"),
                fetch_log=fetch.log,
            )
        sessions = [
            Session(name=r["name"], info_url=CATALOG, register_url=r["detail_url"],
                    dates=r["dates"], ages=r["ages"], price=r["price"],
                    extractor=self.vendor)
            for r in rows
        ]
        return ExtractResult(
            programs=group_sessions_into_programs(provider, sessions, camp_scoped=True),
            fetch_log=fetch.log,
        )
