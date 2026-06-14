"""Per-town US Sports Camps harvester.

For every town you run, queries all ~27 sports against the US Sports Camps
Algolia index and keeps the 10 nearest camps per sport (filled even when fewer
than 10 are local to the town). Each camp carries a canonical deep link
(BASE_URL + record url) so rows never bounce back to the homepage.

Dedup: within each (town, sport) list, a camp appears at most once (by Algolia
objectID). Per-town lists intentionally overlap across towns — that is the
point of a per-town breakdown (Waltham's basketball 10 and Lexington's
basketball 10 may share camps). Use --global-dedup to instead emit each camp
only once across the whole run.

Usage:
    python -m scripts.ussportscamps_camps --town Waltham
    python -m scripts.ussportscamps_camps --town Waltham,Lexington
    python -m scripts.ussportscamps_camps --all
    python -m scripts.ussportscamps_camps --town Waltham --per-sport 10 \
        --out data/ussportscamps_camps.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import ussportscamps as cfg  # noqa: E402
from config.town_geo import TOWN_GEO  # noqa: E402

ALGOLIA_URL = (
    f"https://{cfg.ALGOLIA_APP_ID}-dsn.algolia.net"
    f"/1/indexes/{cfg.ALGOLIA_INDEX}/query"
)
HEADERS = {
    "X-Algolia-Application-Id": cfg.ALGOLIA_APP_ID,
    "X-Algolia-API-Key": cfg.ALGOLIA_SEARCH_KEY,
    "Content-Type": "application/json",
}
METERS_PER_MILE = 1609.34

FIELDNAMES = [
    "town", "sport", "rank", "camp_title", "brand", "gender",
    "min_age", "max_age", "session_dates", "city", "state",
    "distance_mi", "camp_url", "object_id",
]


def _post(payload: dict) -> dict:
    resp = requests.post(ALGOLIA_URL, headers=HEADERS, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_sport_slugs() -> list[str]:
    """Live sport facet list, falling back to the static config list."""
    try:
        data = _post({"query": "", "hitsPerPage": 0,
                      "facets": ["sportSlug"], "maxValuesPerFacet": 200})
        slugs = sorted(data.get("facets", {}).get("sportSlug", {}).keys())
        if slugs:
            return slugs
    except requests.RequestException as exc:
        print(f"  ! live sport list failed ({exc}); using fallback", file=sys.stderr)
    return list(cfg.SPORT_SLUGS_FALLBACK)


def query_sport(lat: float, lon: float, sport: str, n: int) -> list[dict]:
    """The n nearest camps for one sport around (lat, lon)."""
    payload = {
        "query": "",
        "hitsPerPage": n,
        "aroundLatLng": f"{lat}, {lon}",
        "aroundRadius": "all",          # rank by distance, but do not exclude far camps
        "getRankingInfo": True,
        "facetFilters": [[f"sportSlug:{sport}"]],
    }
    return _post(payload).get("hits", [])


def _fmt_dates(hit: dict) -> str:
    """First few session date ranges as 'M/D/YYYY–M/D/YYYY', semicolon-joined."""
    def day(s: str) -> str:
        return s.split(" ", 1)[0] if s else ""

    begins = hit.get("beginDates") or []
    ends = hit.get("endDates") or []
    out = []
    for i, b in enumerate(begins[:4]):
        e = ends[i] if i < len(ends) else ""
        out.append(f"{day(b)}–{day(e)}" if e else day(b))
    return "; ".join(out)


def hit_to_row(town: str, sport: str, rank: int, hit: dict) -> dict:
    addr = hit.get("address") or {}
    geo_m = (hit.get("_rankingInfo") or {}).get("geoDistance")
    gender = hit.get("gender") or []
    return {
        "town": town,
        "sport": hit.get("sportTitle") or sport,
        "rank": rank,
        "camp_title": hit.get("title", ""),
        "brand": hit.get("brand", ""),
        "gender": "/".join(gender),
        "min_age": hit.get("minAge", ""),
        "max_age": hit.get("maxAge", ""),
        "session_dates": _fmt_dates(hit),
        "city": addr.get("city", "") or "",
        "state": addr.get("state", "") or "",
        "distance_mi": round(geo_m / METERS_PER_MILE, 1) if geo_m is not None else "",
        "camp_url": cfg.BASE_URL + hit["url"] if hit.get("url") else "",
        "object_id": hit.get("objectID", ""),
    }


def run(towns: list[str], per_sport: int, sports: list[str],
        global_dedup: bool, delay: float) -> list[dict]:
    rows: list[dict] = []
    seen_global: set[str] = set()
    for town in towns:
        geo = TOWN_GEO.get(town)
        if not geo:
            print(f"! unknown town '{town}' (not in config/town_geo.py); skipping",
                  file=sys.stderr)
            continue
        lat, lon = geo[0], geo[1]
        print(f"\n=== {town} ({lat}, {lon}) — {len(sports)} sports ===")
        for sport in sports:
            try:
                hits = query_sport(lat, lon, sport, per_sport)
            except requests.RequestException as exc:
                print(f"  ! {sport}: query failed ({exc})", file=sys.stderr)
                continue

            kept = 0
            seen_list: set[str] = set()          # dedup within this (town, sport)
            for hit in hits:
                oid = hit.get("objectID")
                if not oid or oid in seen_list:
                    continue
                if global_dedup and oid in seen_global:
                    continue
                seen_list.add(oid)
                seen_global.add(oid)
                kept += 1
                rows.append(hit_to_row(town, sport, kept, hit))
                if kept >= per_sport:
                    break
            print(f"  {sport:24} {kept:>3} camps")
            if delay:
                time.sleep(delay)
    return rows


def write_csv(rows: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _gender_label(raw: str) -> str:
    parts = [p for p in (raw or "").split("/") if p]
    names = {"all": "Co-ed", "male": "Boys", "female": "Girls"}
    return " & ".join(names.get(p, p.title()) for p in parts) or "—"


def write_txt(rows: list[dict], out_path: Path, towns: list[str]) -> None:
    """Human-readable report, grouped by town then sport."""
    from datetime import datetime

    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    bar = "=" * 70
    sub = "-" * 70

    by_town: dict[str, list[dict]] = {}
    for r in rows:
        by_town.setdefault(r["town"], []).append(r)

    for town in towns:
        trows = by_town.get(town)
        if not trows:
            continue
        sports = {}
        for r in trows:
            sports.setdefault(r["sport"], []).append(r)
        lines.append(bar)
        lines.append(f"US SPORTS CAMPS — {town.upper()}, MA")
        lines.append(f"Generated: {datetime.now():%Y-%m-%d %H:%M}")
        lines.append(f"{len(trows)} camps across {len(sports)} sports "
                     f"(nearest first, per sport)")
        lines.append(bar)
        lines.append("")
        for sport in sorted(sports):
            camps = sports[sport]
            lines.append(f"{sport.upper()}  ({len(camps)})")
            lines.append(sub)
            for r in camps:
                ages = f"Ages {r['min_age']}-{r['max_age']}" if r["min_age"] != "" else "Ages n/a"
                loc = ", ".join(p for p in (r["city"], r["state"]) if p) or "Location n/a"
                dist = f"{r['distance_mi']} mi" if r["distance_mi"] != "" else "distance n/a"
                lines.append(f"{int(r['rank']):>2}. {r['camp_title']}")
                brand = f"{r['brand']} | " if r["brand"] else ""
                lines.append(f"    {brand}{ages} | {_gender_label(r['gender'])} | {dist} ({loc})")
                if r["session_dates"]:
                    lines.append(f"    Sessions: {r['session_dates']}")
                lines.append(f"    {r['camp_url']}")
                lines.append("")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--town", help="town name or comma-separated list (e.g. Waltham,Lexington)")
    grp.add_argument("--all", action="store_true", help="run every town in config/town_geo.py")
    ap.add_argument("--per-sport", type=int, default=cfg.CAMPS_PER_SPORT,
                    help=f"camps per sport (default {cfg.CAMPS_PER_SPORT})")
    ap.add_argument("--sports", help="comma-separated sport slugs to override the live list")
    ap.add_argument("--global-dedup", action="store_true",
                    help="emit each camp only once across the whole run")
    ap.add_argument("--delay", type=float, default=cfg.REQUEST_DELAY_S,
                    help="seconds between queries")
    ap.add_argument("--out", default="data/ussportscamps_camps.csv",
                    help="output CSV path")
    ap.add_argument("--txt", nargs="?", const="", default=None,
                    help="also write a neat text report (default: sibling .txt of --out)")
    args = ap.parse_args(argv)

    if args.all:
        towns = list(TOWN_GEO.keys())
    else:
        towns = [t.strip() for t in args.town.split(",") if t.strip()]

    if args.sports:
        sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    else:
        sports = fetch_sport_slugs()
    print(f"Sports ({len(sports)}): {', '.join(sports)}")

    rows = run(towns, args.per_sport, sports, args.global_dedup, args.delay)

    out_path = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    write_csv(rows, out_path)
    uniq = len({r["object_id"] for r in rows})
    print(f"\nWrote {len(rows)} rows ({uniq} unique camps) → {out_path}")

    if args.txt is not None:
        txt_arg = args.txt or str(out_path.with_suffix(".txt"))
        txt_path = (ROOT / txt_arg) if not Path(txt_arg).is_absolute() else Path(txt_arg)
        write_txt(rows, txt_path, towns)
        print(f"Wrote text report → {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
