"""Tests for scripts/score_town.py — fuzzy program matcher + eval metrics."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.score_town import EVAL_COLUMNS, score_town  # noqa: E402

TOWN = "Testville"
SLUG = "testville"

BASELINE_COLUMNS = [
    "name",
    "register_url",
    "platform",
    "dates",
    "ages",
    "price",
    "kind",
    "source_url",
]


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    baseline_root = tmp_path / "_baseline"
    data_root = tmp_path / "data"

    baseline_rows = [
        # exact match
        {
            "name": "Robotics Camp",
            "register_url": "https://rec.example.com/program_details.aspx?ProgramID=1",
            "platform": "myrec",
        },
        # fuzzy match: published as "Specialty Camps: Musical Theater"
        {
            "name": "Musical Theater Camp",
            "register_url": "https://rec.example.com/program_details.aspx?ProgramID=2",
            "platform": "myrec",
        },
        # URL match despite a totally different name
        {
            "name": "Some Old Name",
            "register_url": "https://other.example.org/register?id=77",
            "platform": "custom",
        },
        # miss — never published
        {
            "name": "Pottery Camp",
            "register_url": "https://missing.example.net/camp",
            "platform": "custom",
        },
    ]
    _write_csv(
        baseline_root / SLUG / "camp_sessions.csv", BASELINE_COLUMNS, baseline_rows
    )
    providers = sorted(
        {"rec.example.com", "other.example.org", "missing.example.net"}
    )
    (baseline_root / SLUG / "baseline.json").write_text(
        json.dumps(
            {
                "town": TOWN,
                "provider_count": len(providers),
                "total_sessions": len(baseline_rows),
                "providers": [
                    {"host": h, "platform": "x", "session_count": 1, "register_urls": []}
                    for h in providers
                ],
            }
        ),
        encoding="utf-8",
    )

    published_rows = [
        {
            "name": "Robotics Camp",
            "register_url": "https://rec.example.com/program_details.aspx?ProgramID=1",
            "platform": "myrec",
            "parent_verdict": "parent_ready",
        },
        {
            "name": "Specialty Camps: Musical Theater",
            "register_url": "https://rec.example.com/program_details.aspx?ProgramID=2-other",
            "platform": "myrec",
            "parent_verdict": "brochure_only",
        },
        {
            "name": "Renamed Program",
            "register_url": "https://www.other.example.org/register?id=77",
            "platform": "custom",
            "parent_verdict": "parent_ready",
        },
        # precision miss: host not in baseline providers
        {
            "name": "Adult Yoga",
            "register_url": "https://unrelated.example.io/x",
            "platform": "custom",
            "parent_verdict": "wrong_audience",
        },
    ]
    _write_csv(
        data_root / SLUG / "phase_b5" / "camp_sessions.csv",
        [*BASELINE_COLUMNS, "parent_verdict"],
        published_rows,
    )
    return baseline_root, data_root


def test_score_town_matching_and_metrics(tmp_path):
    baseline_root, data_root = _setup(tmp_path)
    result = score_town(TOWN, baseline_root=baseline_root, data_root=data_root)

    # exact + URL match are strict; fuzzy adds Musical Theater; Pottery missing.
    assert result["baseline_programs"] == 4
    assert result["recall_strict"] == 0.5
    assert result["recall_fuzzy"] == 0.75
    assert result["unmatched_programs"] == [
        {"host": "missing.example.net", "name": "Pottery Camp"}
    ]

    # sessions matched by canonical register_url: ProgramID=1 and id=77 (www-insensitive)
    assert result["session_recall"] == 0.5

    # precision: 3 of 4 published on baseline hosts w/ acceptable verdict
    assert result["precision"] == 0.75

    # providers covered: rec.example.com + other.example.org of 3
    assert result["providers_covered_count"] == 2
    assert result["provider_total"] == 3


def test_score_town_appends_eval_history(tmp_path):
    baseline_root, data_root = _setup(tmp_path)
    score_town(TOWN, baseline_root=baseline_root, data_root=data_root)
    score_town(TOWN, baseline_root=baseline_root, data_root=data_root)

    history = data_root / SLUG / "eval_history.csv"
    assert history.exists()
    with open(history, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == EVAL_COLUMNS
        rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["published_rows"] == "4"


def test_score_town_as_function_no_subprocess(tmp_path):
    # Task 0.2: score_town() callable directly; result dict has the gate metrics.
    baseline_root, data_root = _setup(tmp_path)
    result = score_town(
        TOWN, baseline_root=baseline_root, data_root=data_root, write_history=False
    )
    assert not (data_root / SLUG / "eval_history.csv").exists()
    for key in ("recall_strict", "recall_fuzzy", "session_recall", "precision"):
        assert 0.0 <= result[key] <= 1.0


def test_score_town_no_published_data(tmp_path):
    baseline_root, _ = _setup(tmp_path)
    empty_data = tmp_path / "empty_data"
    result = score_town(
        TOWN, baseline_root=baseline_root, data_root=empty_data, write_history=False
    )
    assert result["published_rows"] == 0
    assert result["recall_fuzzy"] == 0.0
    assert result["precision"] == 0.0
