"""{TOWN}_INSTITUTION_CAMPS.txt — sectioned list of camps hosted by colleges and
schools (discovery-expansion roadmap, Threads 2 & 3).

Classifies each published camp by the kind of institution hosting it (college,
private/prep school, public school, trade/vocational) using the curated
registries first, then domain heuristics so dynamically-discovered institutions
(any `.edu`, any `.k12.*`) are categorized too. Rows that aren't from an
institution are simply omitted from this file (they still appear in the normal
camp list).
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from config.college_registry import colleges_for
from config.school_registry import schools_for

_SECTIONS = [
    ("college", "COLLEGES & UNIVERSITIES"),
    ("private", "PRIVATE / PREP SCHOOLS"),
    ("public", "PUBLIC SCHOOLS"),
    ("trade", "TRADE / VOCATIONAL SCHOOLS"),
]
_SCHOOL_TYPE_TO_KIND = {
    "private": "private", "public_high": "public",
    "public_district": "public", "trade": "trade",
}


def _host(url: str) -> str:
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def institution_kind(host: str, town: str) -> str | None:
    """Return 'college' | 'private' | 'public' | 'trade', or None if `host` is not
    an institution. Curated registries win; then domain heuristics."""
    host = (host or "").lower()
    if not host:
        return None
    for c in colleges_for(town):
        ch = c["host"].lower()
        if host == ch or host.endswith("." + ch):
            return "college"
    for s in schools_for(town):
        sh = s["host"].lower()
        if host == sh or host.endswith("." + sh):
            return _SCHOOL_TYPE_TO_KIND.get(s.get("type", ""), "public")
    # Heuristics for institutions not in the curated registries (dynamic half).
    if host.endswith(".edu"):
        return "college"
    if host.endswith(".k12.ma.us") or "publicschools" in host or "publicschool" in host:
        return "public"
    if "academy" in host or "prepschool" in host or host.endswith("school.org"):
        return "private"
    return None


def _fmt_row(r: dict) -> str:
    lines = [f"  • {r.get('name', '').strip()}"]
    meta = " | ".join(
        x for x in (r.get("dates", "").strip(), r.get("ages", "").strip(), r.get("price", "").strip()) if x
    )
    if meta:
        lines.append(f"      {meta}")
    url = (r.get("register_url") or r.get("info_url") or "").strip()
    if url:
        lines.append(f"      {url}")
    return "\n".join(lines)


def write_institution_camps_txt(town: str, rows: list[dict], out_path: str | Path) -> Path:
    """Write the sectioned institution-camps file for one town. Returns the path."""
    out_path = Path(out_path)
    buckets: dict[str, list[dict]] = {k: [] for k, _ in _SECTIONS}
    for r in rows:
        kind = institution_kind(_host(r.get("info_url") or r.get("register_url") or ""), town)
        if kind in buckets:
            buckets[kind].append(r)

    total = sum(len(v) for v in buckets.values())
    out: list[str] = [
        "=" * 72,
        f"{town.upper()} — COLLEGE & SCHOOL CAMPS",
        "=" * 72,
        f"Institution-hosted camps found: {total}",
        "  " + ", ".join(f"{label.split('/')[0].strip().title()}: {len(buckets[k])}"
                          for k, label in _SECTIONS),
        "",
    ]
    for key, label in _SECTIONS:
        items = buckets[key]
        if not items:
            continue
        out.append("-" * 72)
        out.append(f"{label}  ({len(items)})")
        out.append("-" * 72)
        for r in sorted(items, key=lambda x: (_host(x.get("info_url") or x.get("register_url") or ""),
                                              x.get("name", ""))):
            out.append(_fmt_row(r))
            out.append("")
    if total == 0:
        out.append("(No college- or school-hosted camps identified for this town yet.)")
    out_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return out_path
