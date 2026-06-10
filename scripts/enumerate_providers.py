"""Enumerate every camp for a town's providers across all platforms.

Usage:
  ./venv/bin/python scripts/enumerate_providers.py --town Lexington
  ./venv/bin/python scripts/enumerate_providers.py --urls https://a.com https://b.com

Detailed plain-English log written to logs/session_<date>.log by default.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import SETTINGS  # noqa: E402
from src.data_layout import session_log_path  # noqa: E402
from src.sessions import (  # noqa: E402
    enumerate_town,
    print_enumeration_summary,
    write_session_outputs,
)

SETTINGS["user_agent"] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--town", default="Lexington")
    ap.add_argument("--urls", nargs="*", help="explicit provider URLs (overrides --town)")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Detailed session log path (default: logs/session_<timestamp>.log)",
    )
    args = ap.parse_args()

    log_file = args.log_file or str(session_log_path(args.town))

    urls = args.urls
    n_providers = len(urls) if urls else "auto"
    print(f"Enumerating {n_providers} providers for {args.town}")
    print(f"Detailed log: {log_file}\n")

    results = await enumerate_town(
        args.town,
        urls=urls,
        concurrency=args.concurrency,
        log_file=log_file,
    )
    total = print_enumeration_summary(results)
    csv_path, txt_path, _ = write_session_outputs(args.town, results)

    print(f"\nTotal: {total} camps across {len([r for r in results if r.get('sessions')])} providers")
    print(f"Wrote {csv_path}")
    print(f"Wrote {txt_path}")
    print(f"Detailed log: {log_file}")


if __name__ == "__main__":
    asyncio.run(main())
