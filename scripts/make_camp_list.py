"""Render the engine's four CSVs into a parent-readable camp list TXT.

Usage: python -m scripts.make_camp_list --town lexington
Writes data/<town>/engine/camp_list.txt
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.model import read_output  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--town", required=True)
    args = ap.parse_args()
    out_dir = Path("data") / args.town.lower() / "engine"
    data = read_output(out_dir)

    providers = {p.provider_id: p for p in data["providers"]}
    programs = {p.program_id: p for p in data["programs"]}
    sessions_by_program = defaultdict(list)
    for s in data["sessions"]:
        sessions_by_program[s.program_id].append(s)
    programs_by_provider = defaultdict(list)
    for p in data["programs"]:
        programs_by_provider[p.provider_id].append(p)

    total_sessions = len(data["sessions"])
    ready = sum(1 for s in data["sessions"] if s.verdict == "parent_ready")
    lines = [
        f"{args.town.upper()} — YOUTH SUMMER CAMPS (engine v3)",
        f"Providers: {sum(1 for v in providers.values() if programs_by_provider[v.provider_id])}"
        f" with camps / {len(providers)} checked   "
        f"Programs: {len(programs)}   Sessions: {total_sessions}   "
        f"register-verified: {ready}",
        "=" * 78,
    ]

    for pid, provider in sorted(providers.items(), key=lambda kv: kv[1].host):
        progs = programs_by_provider.get(pid)
        if not progs:
            continue
        lines += ["", f"## {provider.name}  ({provider.host})  [{provider.vendor}]",
                  f"   {len(progs)} program(s)"]
        for prog in sorted(progs, key=lambda p: p.name.lower()):
            lines.append(f"  • {prog.name}")
            if prog.info_url:
                lines.append(f"      info: {prog.info_url}")
            for s in sorted(sessions_by_program.get(prog.program_id, []),
                            key=lambda s: (s.dates, s.name)):
                meta = " | ".join(x for x in (s.dates, s.ages, s.price) if x)
                tag = " ✓register-verified" if s.verdict == "parent_ready" else ""
                extra = f" — {meta}" if meta else ""
                if meta or tag or s.info_url != prog.info_url:
                    lines.append(f"      - {s.name}{extra}{tag}")

    gaps = data["gaps"]
    if gaps:
        lines += ["", "=" * 78, f"## Not published — {len(gaps)} diagnosed gap(s) (see gaps.csv)"]
        by_reason = defaultdict(int)
        for g in gaps:
            by_reason[g.reason] += 1
        lines.append("   " + ", ".join(f"{r}: {n}" for r, n in sorted(by_reason.items())))

    out = out_dir / "camp_list.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
