"""Human-readable mirror of data/camp_links.csv."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from src.link_quality import drop_reason, is_quality_camp_link

from src.data_layout import camp_links_csv

CAMP_LINKS_TXT_PATH = camp_links_csv().with_suffix(".txt")

_SOURCE_ORDER = {
    "registration": 0,
    "camp_host": 1,
    "directory": 2,
    "guide_referral": 3,
    "search": 4,
}


def host_of(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def _fmt_time(iso: str) -> str:
    if not iso:
        return ""
    return iso.replace("T", " ").replace("+00:00", " UTC")[:19]


def write_camp_links_txt(
    rows: list[dict],
    *,
    txt_path: Path | str = CAMP_LINKS_TXT_PATH,
    quality_only: bool = True,
) -> Path:
    """Write organized camp link catalog. Returns txt_path."""
    path = Path(txt_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    raw_total = len(rows)
    slop: list[tuple[str, dict]] = []
    if quality_only:
        kept: list[dict] = []
        for row in rows:
            reason = drop_reason(row.get("url", ""), row.get("link_text", ""))
            if reason:
                slop.append((reason, row))
            else:
                kept.append(row)
        rows = kept
    else:
        slop = []

    if not rows and not slop:
        path.write_text(
            "╔══════════════════════════════════════════════════════════════════════╗\n"
            "║  CAMP LINKS — harvested youth camp URLs                              ║\n"
            "╚══════════════════════════════════════════════════════════════════════╝\n\n"
            "No camp links yet.\n",
            encoding="utf-8",
        )
        return path

    by_host: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_host[host_of(row.get("url", ""))].append(row)

    by_source = Counter(r.get("source_type", "?") for r in rows)
    by_town = Counter(r.get("town_hint", "?") for r in rows)
    by_phase = Counter(r.get("found_via", "?") for r in rows)

    lines = [
        "╔══════════════════════════════════════════════════════════════════════╗",
        "║  CAMP LINKS — quality-filtered youth camp URLs (Phase B)               ║",
        "╚══════════════════════════════════════════════════════════════════════╝",
        "",
        "┌─ SUMMARY ─────────────────────────────────────────────────────────────┐",
        f"│  Shown (quality) .... {len(rows):>5}                                      │",
        f"│  Filtered as slop ... {len(slop):>5}   (of {raw_total} raw in CSV)           │",
        f"│  Unique providers ... {len(by_host):>5}                                      │",
        "├───────────────────────────────────────────────────────────────────────┤",
    ]
    for town, n in sorted(by_town.items()):
        lines.append(f"│  Town: {town:<20} {n:>5} links                              │")
    lines.append("├───────────────────────────────────────────────────────────────────────┤")
    for stype in sorted(by_source.keys(), key=lambda t: (_SOURCE_ORDER.get(t, 99), t)):
        lines.append(f"│  {stype:<18} {by_source[stype]:>5}                                      │")
    lines.append("├───────────────────────────────────────────────────────────────────────┤")
    for phase, n in sorted(by_phase.items()):
        lines.append(f"│  Found via Phase {phase:<10} {n:>5}                                      │")
    lines.extend(
        [
            "└───────────────────────────────────────────────────────────────────────┘",
            "",
            "┌─ PROVIDER INDEX ──────────────────────────────────────────────────────┐",
        ]
    )
    for i, (host, group) in enumerate(
        sorted(by_host.items(), key=lambda x: (-len(x[1]), x[0])), 1
    ):
        label = group[0].get("link_text", "").strip() or host
        if len(label) > 42:
            label = label[:39] + "..."
        lines.append(f"│  {i:>3}. {host:<36} ({len(group):>2})  {label:<24} │")
    lines.extend(["└───────────────────────────────────────────────────────────────────────┘", ""])

    for host, group in sorted(by_host.items(), key=lambda x: (-len(x[1]), x[0])):
        title = group[0].get("link_text", "").strip() or host
        types = Counter(r.get("source_type", "?") for r in group)
        type_str = ", ".join(f"{t}({n})" for t, n in sorted(types.items()))
        lines.extend(
            [
                "",
                "═" * 74,
                f"  ▶ {host.upper()}",
                f"    {title}",
                f"    {len(group)} link(s)  ·  {type_str}",
                "─" * 74,
            ]
        )
        for j, row in enumerate(
            sorted(group, key=lambda r: (_SOURCE_ORDER.get(r.get("source_type", ""), 99), r.get("url", ""))),
            1,
        ):
            stype = row.get("source_type", "")
            text = (row.get("link_text") or "").strip() or "(no title)"
            lines.append(f"  [{j}] {text}")
            lines.append(f"      URL ........ {row.get('url', '')}")
            lines.append(f"      Type ....... {stype}")
            if row.get("found_via"):
                lines.append(f"      Phase ...... {row['found_via']}")
            if row.get("found_on_page"):
                src = row["found_on_page"]
                if len(src) > 68:
                    src = src[:65] + "..."
                lines.append(f"      Found on ... {src}")
            if row.get("discovered_at"):
                lines.append(f"      Discovered . {_fmt_time(row['discovered_at'])}")
            lines.append("")

    if slop:
        lines.extend(
            [
                "",
                "═" * 74,
                f"  FILTERED OUT ({len(slop)} slop links — not shown above)",
                "─" * 74,
            ]
        )
        by_reason: dict[str, list[dict]] = defaultdict(list)
        for reason, row in slop:
            by_reason[reason].append(row)
        for reason in sorted(by_reason.keys(), key=lambda r: -len(by_reason[r])):
            lines.append(f"  [{len(by_reason[reason])}×] {reason}")
            for row in by_reason[reason][:3]:
                lines.append(f"       · {row.get('url', '')[:68]}")
            if len(by_reason[reason]) > 3:
                lines.append(f"       · ... and {len(by_reason[reason]) - 3} more")
            lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def write_camp_links_txt_from_csv(
    csv_path: Path | str = "data/camp_links.csv",
    *,
    txt_path: Path | str = CAMP_LINKS_TXT_PATH,
) -> Path:
    csv_file = Path(csv_path)
    if not csv_file.exists():
        return write_camp_links_txt([], txt_path=txt_path)
    with open(csv_file, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return write_camp_links_txt(rows, txt_path=txt_path)
