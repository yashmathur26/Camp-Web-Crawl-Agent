"""HUB ADAPTER ROADMAP H0.6 — summer-window season filter (start_date based).

Hub searches return year-round programs (verified live: the Skyhawks 02421 pull
contained Sep, Oct, Nov, Dec, and Jan-15 sessions). These must be dropped for
summer scope. Unlike relevance.classify_session (which sniffs the *name* for
season words), this filter parses the row's actual `start_date` / `dates` and
keeps it only when the start falls inside [hub_season_start, hub_season_end]
of the configured season_year.

Asymmetric: a row with NO parseable date is KEPT (absence of a date is not
evidence of being off-season) — but it is flagged season_source="undated" so
the caller can audit. A row with a parseable, out-of-window date is dropped.
"""

from __future__ import annotations

import re
from datetime import date

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "7/6/2026", "7/6", "07-06-2026"
_NUMERIC_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")
# "2026-07-06" (ISO)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
# "July 6, 2026" / "Jul 6" / "Aug. 10"
_MONTH_NAME_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z.]*\s+(\d{1,2})(?:,?\s*(\d{4}))?\b",
    re.I,
)


def _season_bounds(year: int, start_mmdd: str, end_mmdd: str) -> tuple[date, date]:
    sm, sd = (int(x) for x in start_mmdd.split("-"))
    em, ed = (int(x) for x in end_mmdd.split("-"))
    return date(year, sm, sd), date(year, em, ed)


def parse_start_date(blob: str, *, default_year: int) -> date | None:
    """First parseable date in a blob, as a date (year defaulted when absent)."""
    if not blob:
        return None
    iso = _ISO_RE.search(blob)
    if iso:
        y, m, d = (int(g) for g in iso.groups())
        try:
            return date(y, m, d)
        except ValueError:
            return None
    nm = _MONTH_NAME_RE.search(blob)
    if nm:
        mon = _MONTHS.get(nm.group(1).lower())
        d = int(nm.group(2))
        y = int(nm.group(3)) if nm.group(3) else default_year
        if mon:
            try:
                return date(y, mon, d)
            except ValueError:
                return None
    num = _NUMERIC_RE.search(blob)
    if num:
        m, d = int(num.group(1)), int(num.group(2))
        y = num.group(3)
        if y:
            y = int(y)
            if y < 100:
                y += 2000
        else:
            y = default_year
        if 1 <= m <= 12 and 1 <= d <= 31:
            try:
                return date(y, m, d)
            except ValueError:
                return None
    return None


def in_summer_window(
    blob: str,
    *,
    year: int | None = None,
    start_mmdd: str | None = None,
    end_mmdd: str | None = None,
) -> tuple[bool, str]:
    """(keep, reason). Undated rows are kept (reason 'undated')."""
    from config.settings import SETTINGS

    year = year or int(SETTINGS.get("season_year", 2026))
    start_mmdd = start_mmdd or SETTINGS.get("hub_season_start", "06-01")
    end_mmdd = end_mmdd or SETTINGS.get("hub_season_end", "08-31")
    lo, hi = _season_bounds(year, start_mmdd, end_mmdd)

    dt = parse_start_date(blob, default_year=year)
    if dt is None:
        return True, "undated"
    # Compare on month/day so a date stamped with a different year (e.g. a
    # next-summer listing) is still judged by its month window.
    md = (dt.month, dt.day)
    if (lo.month, lo.day) <= md <= (hi.month, hi.day):
        return True, f"in-window:{dt.isoformat()}"
    return False, f"off-season:{dt.isoformat()}"


def filter_summer(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split rows into (kept, dropped) by start_date summer window.

    Reads start_date, else dates, else details_text. Stamps each kept row with
    season_source ('dated'|'undated') and start_date when found.
    """
    kept: list[dict] = []
    dropped: list[dict] = []
    for row in rows:
        blob = " ".join(
            str(row.get(k, ""))
            for k in ("start_date", "dates", "session_dates", "details_text")
            if row.get(k)
        )
        keep, reason = in_summer_window(blob)
        out = dict(row)
        out["_season_reason"] = reason
        if reason.startswith("in-window") or reason.startswith("off-season"):
            out["season_source"] = "dated"
            out["start_date"] = reason.split(":", 1)[1]
        else:
            out["season_source"] = "undated"
        (kept if keep else dropped).append(out)
    return kept, dropped
