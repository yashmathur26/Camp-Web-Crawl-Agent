"""PART D CLI — unified MA-only camp catalog (3 national hubs + US Sports Camps).

Runs Camp Invention + Skyhawks/Configio + iD Tech (HUB_ADAPTER_ROADMAP) together
with the US Sports Camps Algolia harvester, geo-tags every row to MASSACHUSETTS
ONLY, dedupes across all paths, and writes a combined CSV.

    python -m scripts.run_part_d --town Lexington,Waltham
    python -m scripts.run_part_d --all
    python -m scripts.run_part_d --all --no-ussc --no-gate
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from phase_d.part_d import run_part_d  # noqa: E402


def _default_gate_fetch():
    """A simple live register_url gate fetcher (status, html) via requests."""
    import requests

    def fetch(url: str):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            return r.status_code, r.text
        except Exception:  # noqa: BLE001
            return 0, ""

    return fetch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--town", help="town or comma-separated list (e.g. Lexington,Waltham)")
    grp.add_argument("--all", action="store_true", help="run all 54 Middlesex towns")
    ap.add_argument("--no-ussc", action="store_true", help="skip US Sports Camps")
    ap.add_argument("--no-gate", action="store_true", help="skip the register_url verification gate")
    ap.add_argument("--per-sport", type=int, default=10, help="US Sports Camps camps per sport")
    ap.add_argument("--out", default=None,
                    help="output directory (default: <FIREFLY_DATA_ROOT>/part_d)")
    args = ap.parse_args(argv)

    towns = None if args.all else [t.strip() for t in args.town.split(",") if t.strip()]
    res = run_part_d(
        towns=towns,
        include_ussc=not args.no_ussc,
        per_sport=args.per_sport,
        run_gate=not args.no_gate,
        gate_fetch=None if args.no_gate else _default_gate_fetch(),
        out_dir=args.out,
        ts=datetime.now(timezone.utc).date().isoformat(),
    )
    print("\n=== PART D — MA-only unified catalog ===")
    for k, v in res["reconciliation"].items():
        print(f"  {k}: {v}")
    print(f"\n  rows: {len(res['rows'])}  ->  {res['csv_path']}")
    for a in res["alarms"]:
        print(f"  ALARM: {a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
