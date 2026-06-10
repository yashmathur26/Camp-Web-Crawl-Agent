"""Validate Lexington retune acceptance criteria against session CSV."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_layout import camp_sessions_csv, quality_tier_csv, sessions_verified_csv, town_phase_dir
from src.session_quality import enrollability_score, split_parent_verdicts, split_sessions

SESSIONS = camp_sessions_csv("Lexington")
VERIFIED = sessions_verified_csv("Lexington")


def main() -> int:
    path = VERIFIED if VERIFIED.exists() else SESSIONS
    if not path.exists():
        print("Missing", SESSIONS)
        return 1
    sessions = list(csv.DictReader(open(path, encoding="utf-8")))
    tiers = split_sessions(sessions)
    score, counts = enrollability_score(sessions)
    parent = split_parent_verdicts(sessions)
    has_parent = any(s.get("parent_verdict") for s in sessions)

    lexce = [s for s in tiers["registrable"] if "communityed" in s.get("register_url", "")]
    wrong_state = [
        s for s in tiers["registrable"]
        if any(x in s.get("register_url", "") for x in ("lexingtonky", "jccpgh", "cityoflex.com"))
    ]

    checks = [
        ("Enrollability score >= 50", score >= 50, f"score={score}"),
        ("Registrable tier >= 113 (was ~75-85 parent-ready)", counts["registrable"] >= 113, counts["registrable"]),
        ("Rejected tier catches junk", counts["rejected"] >= 20, counts["rejected"]),
        ("0 wrong-state in registrable", len(wrong_state) == 0, len(wrong_state)),
        ("LexCE registrable rows exist", len(lexce) >= 1, len(lexce)),
    ]
    if has_parent:
        checks.extend(
            [
                (
                    "Parent-ready >= 70 (Phase P)",
                    len(parent["parent_ready"]) >= 70,
                    len(parent["parent_ready"]),
                ),
                (
                    "Brochure-only < 30",
                    len(parent["brochure_only"]) < 30,
                    len(parent["brochure_only"]),
                ),
            ]
        )
    gap_r1 = town_phase_dir("Lexington", "phase_gap") / "audit_round1.json"
    if gap_r1.exists():
        checks.append(
            ("Gap audit round 1 exists", True, str(gap_r1)),
        )

    print("Lexington retune validation")
    print("=" * 50)
    ok = True
    for name, passed, detail in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            ok = False
        print(f"  [{status}] {name} ({detail})")
    print(f"\nTiers: {counts}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
