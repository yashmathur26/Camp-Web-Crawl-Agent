#!/usr/bin/env python3
"""Write a human-readable camp list from pilot FINAL_sessions.csv or engine+gap."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

PILOT_ROOT = Path(__file__).resolve().parent
FINAL_COLUMNS = [
    "town", "name", "register_url", "info_url", "dates", "ages", "price",
    "platform", "source_phase", "verdict",
]


def _town_slug(town: str) -> str:
    return town.lower().replace(" ", "_")


def _host(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower().replace("www.", "")


def _is_waltham_local(row: dict) -> bool:
    blob = " ".join(
        row.get(k, "") or ""
        for k in ("name", "register_url", "info_url", "town")
    ).lower()
    return "waltham" in blob or "watch city" in blob or "0245" in blob


def _load_rows(town: str) -> list[dict]:
    final = PILOT_ROOT / "FINAL_sessions.csv"
    if final.exists():
        rows = []
        with open(final, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("town") or "").lower() == town.lower():
                    rows.append(dict(r))
        if rows:
            return rows

    slug = _town_slug(town)
    data_root = PILOT_ROOT / "data"
    rows: list[dict] = []
    eng = data_root / slug / "engine" / "sessions.csv"
    if eng.exists():
        with open(eng, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "town": town,
                    "name": r.get("name", ""),
                    "register_url": r.get("register_url", ""),
                    "info_url": r.get("info_url", ""),
                    "dates": r.get("dates", ""),
                    "ages": r.get("ages", ""),
                    "price": r.get("price", ""),
                    "platform": r.get("extractor", "engine"),
                    "source_phase": "engine",
                    "verdict": r.get("verdict", ""),
                })
    gap_path = data_root / slug / "phase_gap" / "new_sessions.csv"
    if gap_path.exists():
        with open(gap_path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "town": town,
                    "name": r.get("name", ""),
                    "register_url": r.get("register_url", ""),
                    "info_url": r.get("info_url", ""),
                    "dates": r.get("dates", ""),
                    "ages": r.get("ages", ""),
                    "price": r.get("price", ""),
                    "platform": r.get("platform", "gap"),
                    "source_phase": "phase_c",
                    "verdict": r.get("parent_verdict", ""),
                })

    seen: set[str] = set()
    deduped: list[dict] = []
    for row in rows:
        key = (row.get("register_url") or row.get("info_url") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _fmt_field(label: str, value: str, width: int = 12) -> list[str]:
    value = (value or "").strip()
    if not value:
        return [f"  {label:<{width}} —"]
    lines: list[str] = []
    first = True
    for chunk in value.replace("\n", " ").split():
        if first:
            lines.append(f"  {label:<{width}} {chunk}")
            first = False
        else:
            lines.append(f"  {'':<{width}} {chunk}")
    return lines


def write_readable_camp_list(
    town: str,
    rows: list[dict] | None = None,
    *,
    out_path: Path | None = None,
) -> Path:
    if rows is None:
        rows = _load_rows(town)
    slug = _town_slug(town)
    if out_path is None:
        out_path = PILOT_ROOT / "data" / slug / f"{town.upper()}_CAMPS_LIST.txt"

    local = [r for r in rows if _is_waltham_local(r)]
    other = [r for r in rows if not _is_waltham_local(r)]
    local.sort(key=lambda r: (r.get("name") or "").lower())
    other.sort(key=lambda r: (r.get("name") or "").lower())
    ordered = local + other

    engine_n = sum(1 for r in rows if r.get("source_phase") == "engine")
    gap_n = sum(1 for r in rows if r.get("source_phase") == "phase_c")

    lines: list[str] = [
        f"{town.upper()} SUMMER CAMPS — READABLE LIST",
        "=" * 72,
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Total camps: {len(rows)}  (engine: {engine_n}, gap-fill: {gap_n})",
        f"★ Waltham-local or Waltham-branded: {len(local)}",
        "",
        "★ = name or URL mentions Waltham (handy filter, not a quality guarantee).",
        "Register = where parents sign up. Info = program details page.",
        "",
    ]

    def _section(title: str, section_rows: list[dict], start_num: int) -> int:
        if not section_rows:
            return start_num
        lines.append(title)
        lines.append("-" * 72)
        lines.append("")
        n = start_num
        for row in section_rows:
            star = "★ " if _is_waltham_local(row) else ""
            host = _host(row.get("register_url") or row.get("info_url", ""))
            lines.append(f"{'─' * 72}")
            lines.append(f"  {n}. {star}{row.get('name') or '(unnamed camp)'}")
            lines.extend(_fmt_field("Dates:", row.get("dates", "")))
            lines.extend(_fmt_field("Ages:", row.get("ages", "")))
            lines.extend(_fmt_field("Price:", row.get("price", "")))
            lines.extend(_fmt_field("Register:", row.get("register_url", "")))
            lines.extend(_fmt_field("Info:", row.get("info_url", "")))
            phase = row.get("source_phase", "")
            platform = row.get("platform", "")
            lines.append(f"  {'Source:':<12} {phase}" + (f" ({platform})" if platform else ""))
            if host:
                lines.append(f"  {'Host:':<12} {host}")
            verdict = (row.get("verdict") or "").strip()
            if verdict:
                lines.append(f"  {'Quality:':<12} {verdict}")
            lines.append("")
            n += 1
        return n

    num = 1
    if local:
        num = _section("WALTHAM-LOCAL / WALTHAM-BRANDED CAMPS", local, num)
    if other:
        _section("OTHER CAMPS (regional, guides, nearby towns)", other, num)

    lines.append("=" * 72)
    lines.append(f"End of list — {len(rows)} camps for {town}.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def main() -> int:
    import os
    import sys

    repo = PILOT_ROOT.parents[1]
    sys.path.insert(0, str(repo))
    os.environ.setdefault("FIREFLY_DATA_ROOT", str(PILOT_ROOT / "data"))

    parser = argparse.ArgumentParser(description="Write readable camp list TXT from pilot CSV")
    parser.add_argument("--town", default="Waltham")
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()

    path = write_readable_camp_list(args.town, out_path=args.output)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
