"""Auto-generate human-readable .txt mirrors for every .csv."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def write_csv_bundle(
    csv_path: Path | str,
    rows: list[dict],
    fieldnames: list[str],
    *,
    title: str,
    description: str = "",
) -> tuple[Path, Path]:
    """Write CSV and matching TXT. Returns (csv_path, txt_path)."""
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    txt_path = mirror_csv_to_txt(path, title=title, description=description)
    return path, txt_path


def mirror_csv_to_txt(
    csv_path: Path | str,
    *,
    title: str | None = None,
    description: str = "",
    txt_path: Path | str | None = None,
) -> Path:
    """Regenerate TXT from an existing CSV."""
    csv_file = Path(csv_path)
    out = Path(txt_path) if txt_path else csv_file.with_suffix(".txt")
    if not csv_file.exists() or csv_file.stat().st_size == 0:
        out.write_text(
            _header(title or csv_file.stem, description, 0) + "\nNo rows yet.\n",
            encoding="utf-8",
        )
        return out
    with open(csv_file, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    kind = _detect_kind(csv_file, rows)
    body = _formatters[kind](rows)
    out.write_text(
        _header(title or csv_file.stem, description, len(rows)) + body,
        encoding="utf-8",
    )
    return out


def _header(title: str, description: str, count: int) -> str:
    lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        f"║  {title[:68]:<68} ║",
        "╚══════════════════════════════════════════════════════════════════════╝",
        "",
        f"  Rows: {count}",
    ]
    if description:
        lines.extend(["", f"  {description}", ""])
    lines.append("")
    return "\n".join(lines)


def _detect_kind(path: Path, rows: list[dict]) -> str:
    name = path.name.lower()
    if not rows:
        return "generic"
    cols = set(rows[0].keys())
    if "register_url" in cols and "name" in cols:
        if "parent_verdict" in cols:
            return "parent_sessions"
        if "quality_tier" in cols:
            return "quality_sessions"
        return "sessions"
    if "town_hint" in cols and "source_type" in cols:
        return "camp_links"
    if "classified_as" in cols and "town" in cols:
        return "candidates"
    if "event" in cols and "timestamp" in cols:
        return "harvest_activity"
    if name.startswith("rejected"):
        return "rejected"
    return "generic"


def _fmt_sessions(rows: list[dict]) -> str:
    by_host: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        u = r.get("register_url") or r.get("source_url", "")
        by_host[_host(u) or "unknown"].append(r)
    lines = [
        "─" * 74,
        "  BY PROVIDER",
        "─" * 74,
        "",
    ]
    for host in sorted(by_host.keys(), key=lambda h: (-len(by_host[h]), h)):
        group = by_host[host]
        plat = group[0].get("platform", "?")
        lines.append(f"  ▶ {host}  ({len(group)} sessions)  [{plat}]")
        for r in group[:25]:
            meta = " | ".join(
                x for x in (r.get("dates"), r.get("ages"), r.get("price")) if x
            )
            lines.append(f"    • {r.get('name', 'Unnamed')}")
            if meta:
                lines.append(f"      {meta}")
            lines.append(f"      {r.get('register_url', '')}")
        if len(group) > 25:
            lines.append(f"    ... +{len(group) - 25} more in CSV")
        lines.append("")
    return "\n".join(lines)


def _fmt_quality_sessions(rows: list[dict]) -> str:
    tiers = Counter(r.get("quality_tier", "?") for r in rows)
    lines = ["  Quality tiers:", ""]
    for t, n in tiers.most_common():
        lines.append(f"    {t:<16} {n:>4}")
    lines.append(_fmt_sessions(rows))
    return "\n".join(lines)


def _fmt_parent_sessions(rows: list[dict]) -> str:
    verdicts = Counter(r.get("parent_verdict", "?") for r in rows)
    lines = ["  Parent verdicts:", ""]
    for v, n in verdicts.most_common():
        lines.append(f"    {v:<16} {n:>4}")
    lines.append(_fmt_sessions(rows))
    return "\n".join(lines)


def _fmt_camp_links(rows: list[dict]) -> str:
    by_town = Counter(r.get("town_hint", "?") for r in rows)
    by_type = Counter(r.get("source_type", "?") for r in rows)
    lines = [
        "  By town:",
        *[f"    {t:<20} {n:>4}" for t, n in by_town.most_common()],
        "",
        "  By source type:",
        *[f"    {t:<20} {n:>4}" for t, n in by_type.most_common()],
        "",
        "─" * 74,
        "",
    ]
    for r in rows[:80]:
        title = (r.get("link_text") or "").strip() or r.get("url", "")
        lines.append(f"  • {title[:60]}")
        lines.append(f"    {r.get('url', '')}")
        if r.get("town_hint"):
            lines.append(f"    town: {r['town_hint']}  type: {r.get('source_type', '')}")
        lines.append("")
    if len(rows) > 80:
        lines.append(f"  ... +{len(rows) - 80} more in CSV\n")
    return "\n".join(lines)


def _fmt_candidates(rows: list[dict]) -> str:
    by_town: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_town[r.get("town", "?")].append(r)
    lines = []
    for town in sorted(by_town.keys()):
        group = by_town[town]
        crawled = sum(1 for r in group if r.get("crawled") == "true")
        lines.append(f"  {town}: {len(group)} candidates ({crawled} crawled)")
        for r in sorted(group, key=lambda x: x.get("url", ""))[:15]:
            status = "done" if r.get("crawled") == "true" else "pending"
            lines.append(f"    [{status}] {r.get('title', '')[:50] or _host(r.get('url', ''))}")
            lines.append(f"           {r.get('url', '')}")
        if len(group) > 15:
            lines.append(f"    ... +{len(group) - 15} more")
        lines.append("")
    return "\n".join(lines)


def _fmt_harvest_activity(rows: list[dict]) -> str:
    events = Counter(r.get("event", "?") for r in rows)
    lines = ["  Event counts:", ""]
    for e, n in events.most_common(15):
        lines.append(f"    {e:<28} {n:>5}")
    lines.extend(["", "  Recent events:", ""])
    for r in rows[-40:]:
        lines.append(
            f"  [{r.get('timestamp', '')[:19]}] {r.get('event', '')} "
            f"{r.get('url', '')[:50]}"
        )
    return "\n".join(lines) + "\n"


def _fmt_rejected(rows: list[dict]) -> str:
    reasons = Counter(r.get("reason", "?") for r in rows)
    lines = ["  Rejection reasons:", ""]
    for reason, n in reasons.most_common():
        lines.append(f"    [{n:>3}] {reason}")
    lines.append("")
    for r in rows[:30]:
        lines.append(f"  • {r.get('title', '')[:55]}")
        lines.append(f"    {r.get('url', '')}")
        lines.append(f"    reason: {r.get('reason', '')}")
        lines.append("")
    return "\n".join(lines)


def _fmt_generic(rows: list[dict]) -> str:
    if not rows:
        return ""
    cols = list(rows[0].keys())
    lines = [f"  Columns: {', '.join(cols)}", "", "─" * 74, ""]
    for i, r in enumerate(rows[:60], 1):
        lines.append(f"  [{i}]")
        for c in cols[:8]:
            val = str(r.get(c, ""))[:70]
            if val:
                lines.append(f"      {c}: {val}")
        lines.append("")
    if len(rows) > 60:
        lines.append(f"  ... +{len(rows) - 60} more rows in CSV\n")
    return "\n".join(lines)


_formatters = {
    "sessions": _fmt_sessions,
    "quality_sessions": _fmt_quality_sessions,
    "parent_sessions": _fmt_parent_sessions,
    "camp_links": _fmt_camp_links,
    "candidates": _fmt_candidates,
    "harvest_activity": _fmt_harvest_activity,
    "rejected": _fmt_rejected,
    "generic": _fmt_generic,
}
