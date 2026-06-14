#!/usr/bin/env python3
"""Merge the two Waltham camp sources into one organized CSV + TXT.

Sources:
  1. Engine discovery   -> pilot/w3w_test/waltham_run/waltham_camps.csv
  2. US Sports Camps     -> data/waltham/ussportscamps_camps.csv

Output:
  data/waltham/waltham_ALL_camps.csv   (flat unified table, one row per camp)
  data/waltham/waltham_ALL_camps.txt   (human-readable report, grouped)
"""
from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
ENGINE_CSV = ROOT / "pilot/w3w_test/waltham_run/waltham_camps.csv"
SPORTS_CSV = ROOT / "data/waltham/ussportscamps_camps.csv"
OUT_CSV = ROOT / "data/waltham/waltham_ALL_camps.csv"
OUT_TXT = ROOT / "data/waltham/waltham_ALL_camps.txt"

FIELDS = [
    "source", "category", "camp_name", "brand", "gender", "ages", "dates",
    "price", "location", "distance_mi", "url", "info_url", "verdict", "host",
]


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def load_engine() -> list[dict]:
    rows = []
    with open(ENGINE_CSV, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "source": "Engine",
                "category": "",
                "camp_name": r.get("name", "").strip(),
                "brand": "",
                "gender": "",
                "ages": r.get("ages", "").strip(),
                "dates": r.get("dates", "").strip(),
                "price": r.get("price", "").strip(),
                "location": "",
                "distance_mi": "",
                "url": r.get("register_url", "").strip(),
                "info_url": r.get("info_url", "").strip(),
                "verdict": r.get("verdict", "").strip(),
                "host": r.get("host", "").strip(),
            })
    return rows


def load_sports() -> list[dict]:
    rows = []
    with open(SPORTS_CSV, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            lo, hi = r.get("min_age", "").strip(), r.get("max_age", "").strip()
            ages = f"{lo}-{hi}" if (lo or hi) else ""
            city, state = r.get("city", "").strip(), r.get("state", "").strip()
            loc = ", ".join(p for p in (city, state) if p)
            url = r.get("camp_url", "").strip()
            rows.append({
                "source": "US Sports Camps",
                "category": r.get("sport", "").strip(),
                "camp_name": r.get("camp_title", "").strip(),
                "brand": r.get("brand", "").strip(),
                "gender": r.get("gender", "").strip(),
                "ages": ages,
                "dates": r.get("session_dates", "").strip(),
                "price": "",
                "location": loc,
                "distance_mi": r.get("distance_mi", "").strip(),
                "url": url,
                "info_url": url,
                "verdict": "",
                "host": _host(url),
            })
    return rows


def write_csv(rows: list[dict]) -> None:
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def _fmt_meta(r: dict) -> str:
    bits = []
    if r["brand"]:
        bits.append(f"[{r['brand']}]")
    if r["ages"]:
        bits.append(f"ages {r['ages']}")
    if r["gender"] and r["gender"] != "all":
        bits.append(r["gender"])
    if r["dates"]:
        bits.append(r["dates"])
    if r["price"]:
        bits.append("$" + r["price"].lstrip("$"))
    if r["location"]:
        bits.append(r["location"])
    if r["distance_mi"]:
        bits.append(f"{r['distance_mi']}mi")
    return " · ".join(bits)


def write_txt(engine: list[dict], sports: list[dict]) -> None:
    total = len(engine) + len(sports)
    lines: list[str] = []
    bar = "═" * 70
    lines.append("WALTHAM — ALL SUMMER CAMPS (unified)")
    lines.append(f"Total: {total} camps  ({len(engine)} Engine + {len(sports)} US Sports Camps)")
    lines.append("")

    # --- Source 1: Engine ---
    lines.append(bar)
    lines.append(f"SOURCE 1 — ENGINE (primary-source discovery): {len(engine)} camps")
    lines.append(bar)
    lines.append("")
    for i, r in enumerate(sorted(engine, key=lambda x: x["camp_name"].lower()), 1):
        meta = _fmt_meta(r)
        head = f"{i:>3}. {r['camp_name']}"
        if meta:
            head += f"  —  {meta}"
        lines.append(head)
        tag = f"      {r['host']}"
        if r["verdict"]:
            tag += f"  ({r['verdict']})"
        lines.append(tag)
        lines.append(f"      {r['url']}")
        lines.append("")

    # --- Source 2: US Sports Camps, grouped by sport ---
    by_sport: dict[str, list[dict]] = {}
    for r in sports:
        by_sport.setdefault(r["category"], []).append(r)
    lines.append(bar)
    lines.append(
        f"SOURCE 2 — US SPORTS CAMPS: {len(sports)} camps across "
        f"{len(by_sport)} sports (nearest to Waltham)"
    )
    lines.append(bar)
    lines.append("")
    for sport in sorted(by_sport):
        camps = sorted(by_sport[sport], key=lambda x: float(x["distance_mi"] or 1e9))
        lines.append(f"── {sport} ({len(camps)}) " + "─" * max(0, 50 - len(sport)))
        for r in camps:
            meta = _fmt_meta(r)
            line = f"   • {r['camp_name']}"
            if meta:
                line += f"  —  {meta}"
            lines.append(line)
            lines.append(f"     {r['url']}")
        lines.append("")

    OUT_TXT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    engine = load_engine()
    sports = load_sports()
    # Unified CSV: engine block first, then sports grouped by sport then distance.
    sports_sorted = sorted(
        sports, key=lambda x: (x["category"], float(x["distance_mi"] or 1e9))
    )
    engine_sorted = sorted(engine, key=lambda x: x["camp_name"].lower())
    write_csv(engine_sorted + sports_sorted)
    write_txt(engine, sports)
    print(f"Engine camps:          {len(engine)}")
    print(f"US Sports Camps:       {len(sports)}")
    print(f"TOTAL:                 {len(engine) + len(sports)}")
    print(f"\nCSV -> {OUT_CSV}")
    print(f"TXT -> {OUT_TXT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
