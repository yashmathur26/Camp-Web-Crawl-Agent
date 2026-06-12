"""Regression guardrails against committed baseline snapshots."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

BASELINE_ROOT = Path("data/_baseline")

# Task 5.1 — per-provider floors for Lexington published rows (sessions +
# program fallback rows). Initial values from the execution plan.
# TODO(after Task 4.2 MANUAL VERIFY): update each floor to
# max(1, actual_count - 2) from the fresh run and note counts in the commit.
PROVIDER_FLOORS = {
    "majwhaydenweb.myvscloud.com": 35,
    "lexrecma.myrec.com": 20,
    "lexingtoncommunityed.org": 1,   # raise after measuring actual count
    "fuseprogram.com": 1,
    "vikingcamps.com": 1,
    "goddardschool.com": 1,
    "lexingtonunited.org": 1,
    "lexdebateinstitute.com": 1,
    "lexingtonplaycarecenter.org": 1,
    "lexingtonsymphony.org": 1,
    "ussportscamps.com": 1,
    "massaudubon.org": 1,
    "massgeneral.org": 1,
}


def test_lexington_provider_floors():
    path = Path("data/lexington/phase_b5/camp_sessions.csv")
    if not path.exists():
        pytest.skip("no Lexington B.5 output yet (fresh clone)")
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if "granularity" not in (reader.fieldnames or []):
            pytest.skip(
                "camp_sessions.csv predates the fallback-row pipeline — "
                "re-run B.5 for Lexington, then update PROVIDER_FLOORS"
            )
        rows = list(reader)

    counts: dict[str, int] = {}
    for row in rows:
        # A provider is covered if either side of the row points at it.
        hosts = set()
        for key in ("register_url", "source_url"):
            h = urlparse(row.get(key, "")).netloc.lower()
            if h.startswith("www."):
                h = h[4:]
            if h:
                hosts.add(h)
        for h in hosts:
            counts[h] = counts.get(h, 0) + 1

    failures = [
        f"{host}: {counts.get(host, 0)} < floor {floor}"
        for host, floor in PROVIDER_FLOORS.items()
        if counts.get(host, 0) < floor
    ]
    assert not failures, "provider floors broken:\n" + "\n".join(failures)


def _load_baseline(town: str) -> dict:
    path = BASELINE_ROOT / town.lower() / "baseline.json"
    assert path.exists(), f"Missing {path} — run scripts/capture_baseline.py --town {town}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_lexington_baseline_json_exists_with_providers():
    baseline = _load_baseline("lexington")
    assert baseline["provider_count"] >= 1
    assert baseline["total_sessions"] >= 1
    assert isinstance(baseline["providers"], list)
    for row in baseline["providers"]:
        assert "host" in row
        assert "platform" in row
        assert "session_count" in row
        assert "register_urls" in row


def test_burlington_baseline_json_exists_with_providers():
    baseline = _load_baseline("burlington")
    assert baseline["provider_count"] >= 1
    assert baseline["total_sessions"] >= 1


def test_burlington_baseline_csv_matches_json_total():
    baseline = _load_baseline("burlington")
    csv_path = BASELINE_ROOT / "burlington" / "camp_sessions.csv"
    assert csv_path.exists()
    with open(csv_path, encoding="utf-8") as f:
        count = sum(1 for _ in csv.DictReader(f))
    assert count == baseline["total_sessions"]
