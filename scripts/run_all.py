"""Unified runner CLI — one command, all engines/parts, one big CSV per run.

    # run everything for one or more towns -> runs/<timestamp>/all_camps.csv
    python -m scripts.run_all --town Lexington
    python -m scripts.run_all --town Lexington,Waltham

    # pick a subset of stages (A B engine D C)
    python -m scripts.run_all --town Lexington --only D
    python -m scripts.run_all --town Lexington --skip A,B,C

    # turn on the register_url verification gate for Part D (slower, live checks)
    python -m scripts.run_all --town Lexington --gate

    # tidy the workspace: move old data/logs/trash into archive/<timestamp>/
    python -m scripts.run_all --archive            # do it
    python -m scripts.run_all --archive --dry-run  # preview only

Each run lands in runs/<YYYY-MM-DD_HHMMSS>/ with its own data/, logs/,
manifest.json, and the merged all_camps.csv / all_camps.txt.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.unified_run import STAGE_ORDER, archive_clutter, run_unified  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--town", help="town or comma-separated list (e.g. Lexington,Waltham)")
    ap.add_argument("--only", help="run only these stages (comma list of A,B,engine,D,C)")
    ap.add_argument("--skip", help="skip these stages (comma list of A,B,engine,D,C)")
    ap.add_argument("--gate", action="store_true", help="enable Part D register_url verification gate")
    ap.add_argument("--per-sport", type=int, default=10, help="US Sports Camps camps per sport (Part D)")
    ap.add_argument("--parallel", type=int, default=1,
                    help="run this many town pipelines (A->B->engine) at once "
                         "(2 is safe on 16GB; each town stays full-depth)")
    ap.add_argument("--stage-timeout", type=int, default=None, help="per-stage timeout in seconds (default: none)")
    ap.add_argument("--resume", nargs="?", const="LATEST", default=None,
                    help="resume an existing run instead of starting fresh: "
                         "--resume (latest runs/ folder) or --resume runs/<ts> (specific). "
                         "Nothing is deleted; crawled sources are skipped.")
    ap.add_argument("--archive", action="store_true", help="archive old clutter instead of running")
    ap.add_argument("--dry-run", action="store_true", help="with --archive: preview moves only")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.archive:
        res = archive_clutter(dry_run=args.dry_run)
        verb = "WOULD MOVE" if res["dry_run"] else "MOVED"
        print(f"\n=== ARCHIVE {'(dry run)' if res['dry_run'] else ''} -> {res['dest']} ===")
        for m in res["moved"]:
            print(f"  {verb}: {m}")
        if not res["moved"]:
            print("  (nothing to archive)")
        print(f"\n  kept in data/: {', '.join(res['kept_in_data'])}")
        print("  left untouched: pilot/, pictures/ (move by hand if you want them gone)")
        return 0

    if not args.town:
        ap.error("--town is required (or use --archive)")
    towns = [t.strip() for t in args.town.split(",") if t.strip()]
    only = {s.strip() for s in (args.only or "").split(",") if s.strip()}
    skip = {s.strip() for s in (args.skip or "").split(",") if s.strip()}
    for s in only | skip:
        if s not in STAGE_ORDER:
            ap.error(f"unknown stage {s!r}; valid: {', '.join(STAGE_ORDER)}")

    resume_dir = None
    if args.resume is not None:
        if args.resume == "LATEST":
            runs = sorted((ROOT / "runs").glob("*/"), key=lambda p: p.stat().st_mtime)
            if not runs:
                ap.error("--resume: no existing runs/ folder to resume")
            resume_dir = runs[-1]
        else:
            resume_dir = Path(args.resume)
            if not resume_dir.is_dir():
                ap.error(f"--resume: {resume_dir} is not a directory")
        print(f"RESUMING run: {resume_dir} (nothing deleted; crawled sources skipped)")

    res = run_unified(
        towns, skip=skip, only=only, gate=args.gate,
        per_sport=args.per_sport, stage_timeout=args.stage_timeout,
        town_parallelism=args.parallel, resume_dir=resume_dir,
    )
    m = res["manifest"]
    print("\n=== UNIFIED RUN COMPLETE ===")
    print(f"  workspace: {res['ctx'].run_dir}")
    print(f"  towns: {', '.join(m['towns'])}")
    print("  stages:")
    for s in m["stages"]:
        print(f"    {s['key']:24} {s['status']:12} {s['seconds']}s")
    print(f"  total camps: {m['total_camps']}")
    print(f"  by source: {m['camps_by_source']}")
    print(f"  -> {m['outputs']['merged_csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
