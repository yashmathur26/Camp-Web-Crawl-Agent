"""Score a town's published sessions against data/_baseline/<town>/.

Usage: ./venv/bin/python scripts/score_town.py --town Lexington
Appends one row to data/<town_slug>/eval_history.csv and prints a summary.

Metrics
-------
program_recall_strict   matched baseline programs (exact key or register-URL
                        equality) / total baseline programs
program_recall_fuzzy    strict + same-host fuzzy-name matches / total
session_recall          matched baseline sessions / total baseline sessions
                        (match = canonical register_url equality)
precision               published sessions whose host appears in the baseline
                        provider list AND parent_verdict not in
                        {wrong_audience, off_season} / total published.
                        APPROXIMATION: a published row can be a correct camp on
                        a host the baseline missed; this counts it as a miss.
providers_covered       baseline provider hosts with >=1 published row, as a
                        0-1 ratio of all baseline provider hosts.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rapidfuzz import fuzz  # noqa: E402

from src.textnorm import host_of_url, norm_name  # noqa: E402
from src.urls import normalize_url  # noqa: E402

FUZZY_THRESHOLD = 75

EVAL_COLUMNS = [
    "timestamp",
    "recall_strict",
    "recall_fuzzy",
    "session_recall",
    "precision",
    "providers_covered",
    "published_rows",
]


def _town_slug(town: str) -> str:
    return town.lower().replace(" ", "_")


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _canon(url: str) -> str:
    return normalize_url(url or "").rstrip("/")


def _row_host(row: dict) -> str:
    return host_of_url(row.get("register_url", "")) or host_of_url(
        row.get("source_url", "")
    )


def _group_programs(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Group session rows into programs keyed by (host, norm_name)."""
    programs: dict[tuple[str, str], dict] = {}
    for row in rows:
        host = _row_host(row)
        key = (host, norm_name(row.get("name", "")))
        prog = programs.setdefault(
            key, {"host": host, "name": row.get("name", ""), "urls": set(), "rows": []}
        )
        url = _canon(row.get("register_url", ""))
        if url:
            prog["urls"].add(url)
        prog["rows"].append(row)
    return programs


def _load_baseline(slug: str, baseline_root: Path) -> tuple[list[dict], set[str]]:
    """Baseline session rows + provider hosts.

    NOTE: the committed baseline camp_sessions.csv DOES carry a header row
    (name,register_url,platform,dates,...) — parsed by name, not position.
    """
    rows = _read_csv(baseline_root / slug / "camp_sessions.csv")
    provider_hosts: set[str] = set()
    json_path = baseline_root / slug / "baseline.json"
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        provider_hosts = {
            (p.get("host") or "").lower().removeprefix("www.")
            for p in data.get("providers", [])
            if p.get("host")
        }
    if not provider_hosts:
        provider_hosts = {h for h in (_row_host(r) for r in rows) if h}
    return rows, provider_hosts


def _load_published(slug: str, data_root: Path) -> tuple[list[dict], Path | None]:
    verified = data_root / slug / "phase_p" / "all_verified.csv"
    if verified.exists():
        return _read_csv(verified), verified
    b5 = data_root / slug / "phase_b5" / "camp_sessions.csv"
    if b5.exists():
        return _read_csv(b5), b5
    return [], None


def score_town(
    town: str,
    *,
    baseline_root: Path | str = Path("data/_baseline"),
    data_root: Path | str = Path("data"),
    write_history: bool = True,
) -> dict:
    """Score published sessions vs baseline. Returns the metrics dict."""
    baseline_root = Path(baseline_root)
    data_root = Path(data_root)
    slug = _town_slug(town)

    baseline_rows, provider_hosts = _load_baseline(slug, baseline_root)
    published_rows, published_path = _load_published(slug, data_root)

    base_programs = _group_programs(baseline_rows)
    pub_programs = _group_programs(published_rows)

    pub_urls: set[str] = set()
    for prog in pub_programs.values():
        pub_urls.update(prog["urls"])
    pub_norms_by_host: dict[str, list[str]] = {}
    for (host, norm), _prog in pub_programs.items():
        pub_norms_by_host.setdefault(host, []).append(norm)

    strict_matched = 0
    fuzzy_matched = 0
    unmatched: list[dict] = []
    for key, prog in base_programs.items():
        host, norm = key
        exact = key in pub_programs
        url_match = bool(prog["urls"] & pub_urls)
        fuzzy = exact or url_match
        if not fuzzy:
            for cand in pub_norms_by_host.get(host, []):
                if fuzz.token_set_ratio(norm, cand) >= FUZZY_THRESHOLD:
                    fuzzy = True
                    break
        if exact or url_match:
            strict_matched += 1
        if fuzzy:
            fuzzy_matched += 1
        else:
            unmatched.append(prog)

    base_session_urls = [u for r in baseline_rows if (u := _canon(r.get("register_url", "")))]
    matched_sessions = sum(1 for u in base_session_urls if u in pub_urls)

    published_hosts: set[str] = set()
    for row in published_rows:
        for u in (row.get("register_url", ""), row.get("source_url", "")):
            h = host_of_url(u)
            if h:
                published_hosts.add(h)

    precise = 0
    for row in published_rows:
        verdict = (row.get("parent_verdict") or "").strip()
        host_ok = bool(
            {host_of_url(row.get("register_url", "")), host_of_url(row.get("source_url", ""))}
            & provider_hosts
        )
        if host_ok and verdict not in ("wrong_audience", "off_season"):
            precise += 1

    covered = {h for h in provider_hosts if h in published_hosts}

    n_base_programs = len(base_programs) or 1
    result = {
        "town": town,
        "published_source": str(published_path) if published_path else "",
        "baseline_programs": len(base_programs),
        "baseline_sessions": len(baseline_rows),
        "published_rows": len(published_rows),
        "recall_strict": round(strict_matched / n_base_programs, 4),
        "recall_fuzzy": round(fuzzy_matched / n_base_programs, 4),
        "session_recall": round(
            matched_sessions / (len(base_session_urls) or 1), 4
        ),
        "precision": round(precise / (len(published_rows) or 1), 4),
        "providers_covered": round(len(covered) / (len(provider_hosts) or 1), 4),
        "providers_covered_count": len(covered),
        "provider_total": len(provider_hosts),
        "unmatched_programs": [
            {"host": p["host"], "name": p["name"]} for p in unmatched
        ],
    }

    if write_history:
        history = data_root / slug / "eval_history.csv"
        history.parent.mkdir(parents=True, exist_ok=True)
        new_file = not history.exists()
        with open(history, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=EVAL_COLUMNS)
            if new_file:
                w.writeheader()
            w.writerow(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "recall_strict": result["recall_strict"],
                    "recall_fuzzy": result["recall_fuzzy"],
                    "session_recall": result["session_recall"],
                    "precision": result["precision"],
                    "providers_covered": result["providers_covered"],
                    "published_rows": result["published_rows"],
                }
            )
        result["eval_history"] = str(history)

    return result


def _print_summary(result: dict) -> None:
    print(f"\n=== EVAL: {result['town']} vs baseline ===")
    print(f"published source:   {result['published_source'] or '(none found)'}")
    print(f"baseline programs:  {result['baseline_programs']}")
    print(f"baseline sessions:  {result['baseline_sessions']}")
    print(f"published rows:     {result['published_rows']}")
    print(f"recall_strict:      {result['recall_strict']:.1%}")
    print(f"recall_fuzzy:       {result['recall_fuzzy']:.1%}")
    print(f"session_recall:     {result['session_recall']:.1%}")
    print(f"precision (approx): {result['precision']:.1%}")
    print(
        f"providers_covered:  {result['providers_covered_count']}/{result['provider_total']}"
    )
    unmatched = result["unmatched_programs"]
    if unmatched:
        print(f"\n--- UNMATCHED baseline programs ({len(unmatched)}) — work list ---")
        print(f"{'host':<36} name")
        print("-" * 78)
        for p in sorted(unmatched, key=lambda x: (x["host"], x["name"])):
            print(f"{p['host']:<36} {p['name']}")
    else:
        print("\nAll baseline programs matched.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--town", required=True)
    args = parser.parse_args()
    result = score_town(args.town)
    _print_summary(result)


if __name__ == "__main__":
    main()
