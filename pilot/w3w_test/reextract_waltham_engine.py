#!/usr/bin/env python3
"""Re-extract the Waltham engine with the catalog/multi-page fix, reusing the
registry the fresh run already built (no Phase A/B/C). Refreshes the same
waltham_run/ CSV + TXT so the previously-missed camps (Running Brook sub-camps,
multi-page sites) get added.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # run_pilot / run_waltham_fresh

import run_pilot as rp  # noqa: E402  (sets FIREFLY_* env on import)
import run_waltham_fresh as rwf  # noqa: E402  (reuse the live exporter)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(rwf.OUT_DIR / "reextract.log", mode="w"),
              logging.StreamHandler()],
)


def main() -> int:
    t0 = time.time()
    logging.info("=== Re-extracting Waltham engine (catalog fix) on existing registry ===")
    before = rwf._export("before re-extract")
    logging.info("camps before re-extract: %d", before)
    counts = rp._run_engine("Waltham", fresh=True)  # fresh -> ignore checkpoint, use new code
    logging.info("engine counts: %s", counts)
    after = rwf._export("RE-EXTRACT DONE")
    logging.info("=== done in %.1f min — camps: %d -> %d (Δ%+d) ===",
                 (time.time() - t0) / 60, before, after, after - before)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
