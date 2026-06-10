"""Run B.5 enumeration and write per-provider baseline for regression diffs."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_layout import camp_sessions_csv, town_slug  # noqa: E402
from src.sessions import enumerate_town, host_of, write_session_outputs  # noqa: E402

# Lexington providers used for baseline capture (same set as fingerprint_providers.py).
LEXINGTON_PROVIDER_URLS = [
    "https://lexingtonma.gov/511/Recreation-Community-Programs",
    "https://lexrecma.myrec.com/info/activities/activities.aspx",
    "https://www.jwhayden.org/summer-camp",
    "https://lexingtoncommunityed.org/lexplorations/",
    "https://lexfarm.org/education",
    "https://thewaldorfschool.org/summer",
    "https://summersedgedaycamp.com/",
    "https://lca.edu/summer",
    "https://munroecenter.org/summer-camp.html",
    "https://therobohub.com/summer-camp-2026",
    "https://hancocknurseryschool.org/hns-summer",
    "https://lexingtonunited.org/spring-summer-vacation-clinics",
    "https://vikingcamps.com/locations/lexington",
    "https://lexingtonplaycarecenter.org/summer-camp",
    "https://fuseprogram.com/lexington-vacation-summer-program",
    "https://lexdebateinstitute.com/summer",
    "https://goddardschool.com/schools/ma/lexington/lexington/our-school/special-programs/summer-camp",
    "https://lexingtonsymphony.org/phoenixproject",
    "https://massgeneral.org/children/aspire/apply",
    "https://massaudubon.org/places-to-explore/wildlife-sanctuaries/drumlin-farm",
    "https://ussportscamps.com/basketball/massachusetts/lexington",
]


def _provider_rows(results: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for res in results:
        sessions = res.get("sessions") or []
        rows.append(
            {
                "host": host_of(res.get("url", "")),
                "seed_url": res.get("url", ""),
                "platform": res.get("platform", ""),
                "session_count": len(sessions),
                "register_urls": [s.get("register_url", "") for s in sessions if s.get("register_url")],
            }
        )
    return rows


async def capture_town(
    town: str,
    *,
    urls: list[str] | None = None,
    concurrency: int = 2,
    baseline_root: Path = Path("data/_baseline"),
) -> Path:
    results = await enumerate_town(town, urls=urls, concurrency=concurrency)
    write_session_outputs(town, results)

    providers = _provider_rows(results)
    payload = {
        "town": town,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "provider_count": len(providers),
        "total_sessions": sum(p["session_count"] for p in providers),
        "providers": providers,
    }

    dest = baseline_root / town_slug(town)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "baseline.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    src_csv = camp_sessions_csv(town)
    if src_csv.exists():
        (dest / "camp_sessions.csv").write_text(src_csv.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--town", required=True, help="Town name, e.g. Lexington or Burlington")
    ap.add_argument("--urls", nargs="*", help="Explicit provider seed URLs (overrides town loader)")
    ap.add_argument("--use-lexington-fingerprint", action="store_true", help="Use known Lexington provider list")
    ap.add_argument("--concurrency", type=int, default=2)
    args = ap.parse_args()

    urls = args.urls
    if args.use_lexington_fingerprint:
        urls = LEXINGTON_PROVIDER_URLS

    dest = asyncio.run(capture_town(args.town, urls=urls, concurrency=args.concurrency))
    summary = json.loads((dest / "baseline.json").read_text(encoding="utf-8"))
    print(f"Baseline written: {dest / 'baseline.json'}")
    print(f"  providers={summary['provider_count']}  sessions={summary['total_sessions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
