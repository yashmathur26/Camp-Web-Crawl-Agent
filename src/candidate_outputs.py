"""Human-readable mirror of data/candidates.csv — updated whenever the CSV is saved."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from src.data_layout import candidates_csv

CANDIDATES_TXT_PATH = candidates_csv().with_suffix(".txt")

_TYPE_ORDER = {"directory": 0, "camp": 1, "unknown": 2, "guide": 3}


def host_of(url: str) -> str:
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def write_candidates_txt(
    rows: list[dict],
    *,
    txt_path: Path | str = CANDIDATES_TXT_PATH,
) -> Path:
    """Write a readable summary of candidate provider URLs. Returns txt_path."""
    path = Path(txt_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text(
            "CANDIDATES — provider discovery URLs\n"
            "No candidates yet.\n",
            encoding="utf-8",
        )
        return path

    crawled = sum(1 for r in rows if r.get("crawled", "false") == "true")
    pending = len(rows) - crawled
    preferred = sum(1 for r in rows if r.get("preferred") == "true")
    by_town: Counter[str] = Counter(r.get("town", "?") for r in rows)
    by_phase: Counter[str] = Counter(r.get("phase", "?") for r in rows)
    by_type: Counter[str] = Counter(r.get("classified_as", "?") for r in rows)

    lines = [
        "CANDIDATES — provider discovery URLs",
        f"Total: {len(rows)}   Crawled: {crawled}   Pending: {pending}   Preferred: {preferred}",
        "=" * 72,
        "",
        "## SUMMARY",
        f"{'Town':<20} {'Count':>6}",
        "-" * 28,
    ]
    for town, n in sorted(by_town.items()):
        lines.append(f"{town:<20} {n:>6}")
    lines.extend(
        [
            "",
            f"Phases: {', '.join(f'{p} ({n})' for p, n in sorted(by_phase.items()))}",
            f"Types:  {', '.join(f'{t} ({n})' for t, n in sorted(by_type.items()))}",
            "",
            "## BY TYPE (crawled / pending)",
            f"{'Type':<14} {'Crawled':>8} {'Pending':>8} {'Total':>8}",
            "-" * 42,
        ]
    )
    for ctype in sorted(by_type.keys(), key=lambda t: (_TYPE_ORDER.get(t, 99), t)):
        subset = [r for r in rows if r.get("classified_as") == ctype]
        c = sum(1 for r in subset if r.get("crawled") == "true")
        lines.append(f"{ctype:<14} {c:>8} {len(subset) - c:>8} {len(subset):>8}")

    by_town_rows: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_town_rows[row.get("town", "?")].append(row)

    for town in sorted(by_town_rows.keys()):
        town_rows = by_town_rows[town]
        lines.extend(["", "=" * 72, "", f"## {town.upper()} ({len(town_rows)} candidates)", ""])

        by_class: dict[str, list[dict]] = defaultdict(list)
        for row in town_rows:
            by_class[row.get("classified_as", "unknown")].append(row)

        for ctype in sorted(by_class.keys(), key=lambda t: (_TYPE_ORDER.get(t, 99), t)):
            group = by_class[ctype]
            lines.append(f"### {ctype.upper()} ({len(group)})")
            lines.append("")

            def sort_key(r: dict) -> tuple:
                is_crawled = r.get("crawled") == "true"
                is_pref = r.get("preferred") == "true"
                return (is_crawled, not is_pref, host_of(r.get("url", "")))

            for i, row in enumerate(sorted(group, key=sort_key), 1):
                status = "crawled" if row.get("crawled") == "true" else "pending"
                pref = "preferred" if row.get("preferred") == "true" else "normal"
                title = (row.get("title") or "").strip() or host_of(row.get("url", ""))
                lines.append(f"{i}. {title}")
                lines.append(f"   URL:      {row.get('url', '')}")
                lines.append(f"   Host:     {host_of(row.get('url', ''))}")
                lines.append(f"   Status:   {status}  |  {pref}")
                lines.append(f"   Phase:    {row.get('phase', '')}  |  keyword: {row.get('keyword', '')}")
                if row.get("discovered_at"):
                    lines.append(f"   Found:    {row['discovered_at']}")
                lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def write_candidates_txt_from_csv(
    csv_path: Path | str = "data/candidates.csv",
    *,
    txt_path: Path | str = CANDIDATES_TXT_PATH,
) -> Path:
    """Regenerate candidates.txt from an existing CSV file."""
    csv_file = Path(csv_path)
    if not csv_file.exists():
        return write_candidates_txt([], txt_path=txt_path)
    with open(csv_file, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return write_candidates_txt(rows, txt_path=txt_path)
