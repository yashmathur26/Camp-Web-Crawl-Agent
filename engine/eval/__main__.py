"""CLI: python -m engine.eval --town lexington [--input sessions.csv]
[--offline] [--label name] [--compare a.json b.json]"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.eval.score import (
    HISTORY_DIR,
    format_table,
    load_aliases,
    load_ground_truth,
    load_published,
    score,
    write_history,
)


def _compare(a: str, b: str) -> int:
    pa = json.loads((HISTORY_DIR / a).read_text() if not Path(a).exists() else Path(a).read_text())
    pb = json.loads((HISTORY_DIR / b).read_text() if not Path(b).exists() else Path(b).read_text())
    keys = ["program_recall", "session_recall", "precision", "info_url_validity", "published_rows"]
    print(f"{'metric':<20} {'A: ' + pa.get('label', pa['timestamp']):<24} {'B: ' + pb.get('label', pb['timestamp']):<24} delta")
    for k in keys:
        va, vb = pa.get(k), pb.get(k)
        delta = "" if None in (va, vb) else f"{(vb - va):+.4f}"
        print(f"{k:<20} {str(va):<24} {str(vb):<24} {delta}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--town", help="town name matching ground_truth/<town>.csv")
    ap.add_argument("--input", help="published CSV to score (default: engine output for town)")
    ap.add_argument("--offline", action="store_true", help="skip live info-url validity fetches")
    ap.add_argument("--label", default="", help="history entry label")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help="diff two history entries")
    args = ap.parse_args()

    if args.compare:
        return _compare(*args.compare)
    if not args.town:
        ap.error("--town is required unless --compare is used")

    if args.input:
        input_path = Path(args.input)
    else:
        input_path = Path(f"data/{args.town.lower()}/engine/sessions.csv")
    if not input_path.exists():
        print(f"input not found: {input_path}", file=sys.stderr)
        return 2

    gt = load_ground_truth(args.town)
    published = load_published(input_path)
    metrics = score(
        published, gt,
        check_info_urls=not args.offline,
        aliases=load_aliases(args.town),
    )
    print(f"\nEval — town={args.town}  input={input_path}\n")
    print(format_table(metrics))
    if metrics["unmatched_gt_programs"]:
        print(f"\n  Unmatched GT programs ({len(metrics['unmatched_gt_programs'])}):")
        for miss in metrics["unmatched_gt_programs"][:40]:
            print(f"    - {miss}")
    path = write_history(args.town, metrics, label=args.label)
    print(f"\n  history → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
