"""Regression guardrails against committed baseline snapshots."""

from __future__ import annotations

import csv
import json
from pathlib import Path

BASELINE_ROOT = Path("data/_baseline")


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
