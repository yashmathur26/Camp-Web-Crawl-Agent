"""Phase 0: audit the frozen v2 baseline and write data/junk_audit.csv.

Reads the frozen bad run under data/_baseline_v2/<town>/camp_sessions.csv,
runs src.junk_audit.audit_row on every row, and emits one CSV listing each
junk row with its machine-checkable reason(s). This is the measurable target
that Phases 1-7 must drive toward zero.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.junk_audit import audit_row  # noqa: E402

TOWNS = ["lexington", "burlington"]
BASELINE = Path("data/_baseline_v2")
OUT = Path("data/junk_audit.csv")


def main() -> int:
    rows: list[dict] = []
    totals: dict[str, int] = {}
    per_town: dict[str, dict[str, int]] = {}
    for town in TOWNS:
        path = BASELINE / town / "camp_sessions.csv"
        if not path.exists():
            print(f"missing {path}", file=sys.stderr)
            continue
        counts = {"total": 0, "junk": 0}
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                counts["total"] += 1
                reasons = audit_row(r)
                if not reasons:
                    continue
                counts["junk"] += 1
                for reason in reasons:
                    totals[reason] = totals.get(reason, 0) + 1
                rows.append(
                    {
                        "town": town,
                        "name": r.get("name", ""),
                        "register_url": r.get("register_url", ""),
                        "info_url": r.get("info_url", ""),
                        "reasons": ";".join(reasons),
                    }
                )
        per_town[town] = counts

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["town", "name", "register_url", "info_url", "reasons"]
        )
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {OUT} ({len(rows)} junk rows)")
    for town, c in per_town.items():
        print(f"  {town}: {c['junk']}/{c['total']} rows junk")
    print("  reason breakdown:", dict(sorted(totals.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
